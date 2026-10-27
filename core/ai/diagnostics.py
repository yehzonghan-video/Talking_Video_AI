"""Allowlisted API diagnostics. Never return raw server text or request content."""
import json
import re


MESSAGES = {
    'schema_complexity': 'Response schema has too many states or too much branching.',
    'invalid_schema': 'Response JSON schema was rejected.',
    'model_unsupported': 'Model does not support the requested input or output mode.',
    'invalid_audio': 'Audio format or audio MIME type was rejected.',
    'request_too_large': 'Request size or input token limit was exceeded.',
    'invalid_parameter': 'Request parameter was rejected.',
    'authentication': 'API key was rejected.',
    'invalid_request': 'Request contains an invalid argument.',
    'other_api_error': 'API request failed; unrecognized server text was redacted.',
}
API_FIELDS = ('response_json_schema', 'response_schema', 'response_mime_type',
              'generation_config', 'contents', 'parts', 'inline_data', 'mime_type',
              'file_data', 'file_uri', 'model', 'system_instruction', 'max_output_tokens',
              'temperature', 'maxItems', 'minItems', 'minimum', 'maximum')
STATUSES = {'INVALID_ARGUMENT', 'UNAUTHENTICATED', 'PERMISSION_DENIED', 'NOT_FOUND',
            'RESOURCE_EXHAUSTED', 'UNAVAILABLE', 'INTERNAL', 'DEADLINE_EXCEEDED'}


def api_diagnostic(exc: Exception) -> dict:
    body = getattr(exc, 'details', None) or getattr(exc, 'response_json', None) or {}
    if isinstance(body, dict):
        body = body.get('error', body)
    # Use raw text only for classification in memory. Logs contain fixed templates
    # and known API field names, so echoed transcripts/keys cannot bypass redaction.
    text = (json.dumps(body, ensure_ascii=False, default=lambda _: '') +
            str(getattr(exc, 'message', '') or '')).casefold()
    compact = re.sub(r'[^a-z0-9]', '', text)
    if 'apikeyinvalid' in compact or 'api key not valid' in text:
        cause = 'authentication'
    elif any(s in text for s in ('too many states', 'too much branching', 'schema is too complex', 'schema too complex')):
        cause = 'schema_complexity'
    elif 'audio' in text and any(s in text for s in ('format', 'mime', 'decode', 'encoding', 'unsupported')):
        cause = 'invalid_audio'
    elif any(s in text for s in ('request too large', 'payload size', 'request size', 'token limit', 'maximum number of tokens')):
        cause = 'request_too_large'
    elif ('model' in text or 'json mode' in text) and any(s in text for s in ('not supported', 'does not support', 'unsupported')):
        cause = 'model_unsupported'
    elif 'schema' in text:
        cause = 'invalid_schema'
    elif any(s in text for s in ('fieldviolations', 'unknown name', 'invalid value', 'unsupported parameter', 'invalid parameter')):
        cause = 'invalid_parameter'
    else:
        cause = 'invalid_request' if str(getattr(exc, 'code', None)) == '400' else 'other_api_error'
    status = body.get('status') if isinstance(body, dict) else None
    return {
        'cause': cause, 'provider_message': MESSAGES[cause],
        'api_status': status if isinstance(status, str) and status in STATUSES else None,
        'fields': [field for field in API_FIELDS if field.casefold().replace('_', '') in compact],
    }
