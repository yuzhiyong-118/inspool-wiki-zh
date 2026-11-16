"""可信宿主的无工具 Responses JSON 传输；不授予远端任何本机能力。"""
from __future__ import annotations

import ipaddress
import json
import math
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class ModelError(ValueError):
    """配置、网络或模型输出失败；错误文本不含请求、响应或密钥。"""


_FIELDS = {'provider', 'base_url', 'model', 'api_key_env',
           'timeout_seconds', 'max_output_tokens'}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _positive(value):
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and 0 < value <= threading.TIMEOUT_MAX)
    except OverflowError:
        return False


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelError('模型 JSON 含重复字段')
        result[key] = value
    return result


def _constant(_value):
    raise ModelError('模型 JSON 含非有限数字')


def _loads(data):
    try:
        value = json.loads(data, object_pairs_hook=_object, parse_constant=_constant)
        # 1e999 等合法 JSON 数字也可能溢出为 infinity。
        json.dumps(value, allow_nan=False)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ModelError('模型返回无效 JSON') from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ResponsesTransport:
    """每次调用都是独立请求；配置必须由可信宿主提供，不读取模型配置。"""

    def __init__(self, config, *, environ=None):
        if type(config) is not dict or set(config) != _FIELDS:
            raise ModelError('模型配置必须精确包含约定的六个字段')
        if config['provider'] != 'openai_responses':
            raise ModelError('不支持的模型 provider')
        for field in ('base_url', 'model', 'api_key_env'):
            value = config[field]
            if type(value) is not str or not value.strip() or value != value.strip() or any(ord(c) < 32 for c in value):
                raise ModelError('模型配置字符串无效')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', config['api_key_env']):
            raise ModelError('密钥环境变量名无效')
        try:
            url = urllib.parse.urlsplit(config['base_url'])
            host = url.hostname
            url.port  # 同时验证端口格式。
            loopback = host == 'localhost'
            if host and not loopback:
                try:
                    loopback = ipaddress.ip_address(host).is_loopback
                except ValueError:
                    pass
            if (not host or url.username is not None or url.password is not None
                    or url.query or url.fragment or '\\' in config['base_url']
                    or (url.scheme != 'https' and not (url.scheme == 'http' and loopback))):
                raise ValueError
        except ValueError:
            raise ModelError('模型 URL 仅允许 HTTPS 或本机回环 HTTP，且不能含凭据') from None
        if not _positive(config['timeout_seconds']):
            raise ModelError('模型超时必须为正有限秒数')
        if type(config['max_output_tokens']) is not int or config['max_output_tokens'] <= 0:
            raise ModelError('模型输出上限必须为正整数')
        secret = (os.environ if environ is None else environ).get(config['api_key_env'])
        if type(secret) is not str or not secret.strip() or any(ord(c) < 33 or ord(c) > 126 for c in secret):
            raise ModelError('模型密钥环境变量未提供有效值')
        self._key = secret
        self._url = config['base_url'].rstrip('/') + '/responses'
        self._model = config['model']
        self._timeout = config['timeout_seconds']
        self._tokens = config['max_output_tokens']

    def __call__(self, envelope, *, timeout):
        if not _positive(timeout):
            raise ModelError('调用超时必须为正有限秒数')
        budget = min(timeout, self._timeout)
        deadline = time.monotonic() + budget
        if type(envelope) is not dict or type(envelope.get('system')) is not str or not envelope['system'].strip():
            raise ModelError('模型 envelope 必须含非空 system 字符串')
        try:
            user = json.dumps({k: v for k, v in envelope.items() if k != 'system'},
                              ensure_ascii=False, allow_nan=False)
            body = json.dumps({
                'model': self._model,
                'input': [{'role': 'system', 'content': envelope['system']},
                          {'role': 'user', 'content': user}],
                'text': {'format': {'type': 'json_object'}},
                'store': False, 'tools': [], 'max_output_tokens': self._tokens,
            }, ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ModelError('模型输入必须是有限 JSON 数据') from None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModelError('模型调用超时')
        mailbox = queue.Queue(maxsize=1)

        def invoke():
            try:
                result = self._request(body, deadline)
            except Exception:
                # 不把 urllib 异常、错误响应或模型正文带入上层日志。
                mailbox.put((False, None))
            else:
                mailbox.put((True, result))

        threading.Thread(target=invoke, daemon=True).start()
        try:
            ok, result = mailbox.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            raise ModelError('模型调用超时') from None
        if time.monotonic() >= deadline:
            raise ModelError('模型调用超时')
        if not ok:
            raise ModelError('模型传输或 JSON 输出失败')
        return result

    def _request(self, body, deadline):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        request = urllib.request.Request(self._url, data=body, method='POST', headers={
            'Authorization': 'Bearer ' + self._key,
            'Content-Type': 'application/json', 'Accept': 'application/json',
        })
        with opener.open(request, timeout=max(0.001, deadline - time.monotonic())) as response:
            if response.status != 200 or response.headers.get_content_type() != 'application/json':
                raise ModelError('模型 HTTP 响应无效')
            chunks = []
            size = 0
            while True:
                if time.monotonic() >= deadline:
                    raise ModelError('模型调用超时')
                chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ModelError('模型响应过大')
                chunks.append(chunk)
            data = b''.join(chunks)
        reply = _loads(data.decode('utf-8', errors='strict'))
        if (type(reply) is not dict or reply.get('status') != 'completed'
                or reply.get('error') is not None or reply.get('incomplete_details') is not None):
            raise ModelError('模型未完整完成')
        output = reply.get('output')
        if type(output) is not list:
            raise ModelError('模型 output 必须为数组')
        messages = []
        for item in output:
            if type(item) is not dict:
                raise ModelError('模型输出项无效')
            if item.get('type') == 'reasoning':
                # 供应商的思考元数据不是工具能力，也不进入业务 JSON。
                continue
            if item.get('type') != 'message':
                raise ModelError('模型返回工具或未知输出')
            messages.append(item)
        if len(messages) != 1:
            raise ModelError('模型必须只返回单条消息')
        message = messages[0]
        if (type(message) is not dict or message.get('type') != 'message'
                or message.get('role') != 'assistant' or message.get('status') != 'completed'):
            raise ModelError('模型返回非完整助手消息')
        content = message.get('content')
        if type(content) is not list or not content:
            raise ModelError('模型没有文本输出')
        parts = []
        for part in content:
            if (type(part) is not dict or part.get('type') != 'output_text'
                    or type(part.get('text')) is not str):
                raise ModelError('模型拒绝或返回非文本输出')
            parts.append(part['text'])
        result = _loads(''.join(parts))
        if type(result) is not dict:
            raise ModelError('模型 JSON 必须为单个对象')
        return result
