"""Cliente da API Melhor Envio — OAuth + cotação por produtos."""

from __future__ import annotations

import json
from pathlib import Path
import time
from urllib.parse import urlencode

import requests
from django.conf import settings

TOKEN_FILE = Path(settings.BASE_DIR) / 'melhorenvio_token.json'


class MelhorEnvioError(Exception):
    def __init__(self, message, status_code=None, details=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _base_url() -> str:
    return settings.MELHOR_ENVIO_BASE_URL.rstrip('/')


def _user_agent() -> str:
    return settings.MELHOR_ENVIO_USER_AGENT


def get_access_token() -> str:
    """Prioriza token salvo via OAuth; fallback para MELHOR_ENVIO_TOKEN no .env."""
    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding='utf-8'))
            token = (data.get('access_token') or '').strip() if isinstance(data, dict) else ''
            if token:
                expires_at = _expires_at(data)
                if expires_at and expires_at <= time.time() + 120:
                    data = _refresh_access_token(data)
                    token = (data.get('access_token') or '').strip()
                return token
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    token = (settings.MELHOR_ENVIO_TOKEN or '').strip()
    if token:
        return token

    raise MelhorEnvioError(
        'Melhor Envio ainda não conectado. Configure o app no .env local e autorize pelo site.',
        status_code=503,
    )


def save_token_response(data: dict) -> None:
    stored = dict(data)
    expires_in = _positive_seconds(stored.get('expires_in'))
    if expires_in:
        stored['expires_at'] = int(time.time()) + expires_in
    TOKEN_FILE.write_text(json.dumps(stored, indent=2, ensure_ascii=False), encoding='utf-8')


def _positive_seconds(value):
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _expires_at(data: dict):
    try:
        value = int(data.get('expires_at') or 0)
    except (TypeError, ValueError):
        return None
    if value:
        return value

    expires_in = _positive_seconds(data.get('expires_in'))
    try:
        created_at = int(data.get('created_at') or 0)
    except (TypeError, ValueError):
        created_at = 0
    return created_at + expires_in if created_at and expires_in else None


def _refresh_access_token(current: dict) -> dict:
    refresh_token = (current.get('refresh_token') or '').strip()
    client_id = (settings.MELHOR_ENVIO_CLIENT_ID or '').strip()
    client_secret = (settings.MELHOR_ENVIO_CLIENT_SECRET or '').strip()
    if not refresh_token:
        raise MelhorEnvioError(
            'A autorização do Melhor Envio expirou. Reconecte a integração pelo site.',
            status_code=401,
        )
    if not client_id or not client_secret:
        raise MelhorEnvioError(
            'Configure as credenciais OAuth do Melhor Envio no .env para renovar o acesso.',
            status_code=503,
        )

    try:
        response = requests.post(
            f'{_base_url()}/oauth/token',
            data={
                'grant_type': 'refresh_token',
                'client_id': client_id,
                'client_secret': client_secret,
                'refresh_token': refresh_token,
            },
            headers={'Accept': 'application/json', 'User-Agent': _user_agent()},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise MelhorEnvioError(
            'Não foi possível renovar o acesso ao Melhor Envio agora.', status_code=502
        ) from exc

    try:
        refreshed = response.json()
    except ValueError as exc:
        raise MelhorEnvioError(
            'O Melhor Envio retornou uma resposta inválida ao renovar o acesso.', status_code=502
        ) from exc

    if response.status_code >= 400 or not isinstance(refreshed, dict) or not refreshed.get('access_token'):
        raise MelhorEnvioError(
            'Não foi possível renovar a autorização. Reconecte a integração pelo site.',
            status_code=401 if response.status_code in (400, 401) else 502,
        )

    updated = {**current, **refreshed}
    save_token_response(updated)
    if not updated.get('refresh_token'):
        updated['refresh_token'] = refresh_token
    return updated


def build_authorize_url(state: str = 'patchworks') -> str:
    client_id = (settings.MELHOR_ENVIO_CLIENT_ID or '').strip()
    redirect_uri = (settings.MELHOR_ENVIO_REDIRECT_URI or '').strip()
    if not client_id or not redirect_uri:
        raise MelhorEnvioError(
            'Defina MELHOR_ENVIO_CLIENT_ID e MELHOR_ENVIO_REDIRECT_URI no .env.',
            status_code=503,
        )

    # Scope mínimo para cotação
    scope = 'shipping-calculate shipping-companies'
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'state': state,
        'scope': scope,
    }
    return f"{_base_url()}/oauth/authorize?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    client_id = (settings.MELHOR_ENVIO_CLIENT_ID or '').strip()
    client_secret = (settings.MELHOR_ENVIO_CLIENT_SECRET or '').strip()
    redirect_uri = (settings.MELHOR_ENVIO_REDIRECT_URI or '').strip()

    if not all([client_id, client_secret, redirect_uri]):
        raise MelhorEnvioError(
            'Credenciais OAuth incompletas no .env (CLIENT_ID, CLIENT_SECRET, REDIRECT_URI).',
            status_code=503,
        )

    url = f'{_base_url()}/oauth/token'
    payload = {
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'code': code,
    }

    try:
        response = requests.post(
            url,
            data=payload,
            headers={
                'Accept': 'application/json',
                'User-Agent': _user_agent(),
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise MelhorEnvioError(f'Falha ao trocar code por token: {exc}', status_code=502) from exc

    if response.status_code >= 400:
        details = {}
        try:
            details = response.json()
        except ValueError:
            details = {'raw': response.text[:500]}
        raise MelhorEnvioError(
            details.get('message')
            or details.get('error_description')
            or f'Erro ao obter token (HTTP {response.status_code}).',
            status_code=response.status_code,
            details=details,
        )

    data = response.json()
    if not data.get('access_token'):
        raise MelhorEnvioError('Resposta OAuth sem access_token.', status_code=502, details=data)

    save_token_response(data)
    return data


def _headers():
    return {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {get_access_token()}',
        'User-Agent': _user_agent(),
    }


def _cep_origem_loja() -> str:
    """CEP de origem: Admin (Configuração da loja) com fallback para .env."""
    from core.models import ConfiguracaoLoja

    try:
        return ConfiguracaoLoja.get_solo().cep_digitos
    except Exception:
        return ''.join(ch for ch in str(settings.STORE_CEP) if ch.isdigit())


def calcular_frete_produtos(*, cep_destino: str, products: list[dict], services: str | None = None):
    """POST /api/v2/me/shipment/calculate"""
    cep_origem = _cep_origem_loja()
    cep_destino = ''.join(ch for ch in str(cep_destino) if ch.isdigit())

    if len(cep_origem) != 8:
        raise MelhorEnvioError('CEP de origem da loja inválido.', status_code=500)
    if len(cep_destino) != 8:
        raise MelhorEnvioError('CEP de destino inválido. Informe 8 dígitos.', status_code=400)
    if not products:
        raise MelhorEnvioError('Nenhum produto informado para cotação.', status_code=400)

    payload = {
        'from': {'postal_code': cep_origem},
        'to': {'postal_code': cep_destino},
        'products': products,
        'options': {
            'receipt': False,
            'own_hand': False,
        },
    }
    if services:
        payload['services'] = services

    url = f'{_base_url()}/api/v2/me/shipment/calculate'

    try:
        response = requests.post(url, json=payload, headers=_headers(), timeout=30)
    except requests.RequestException as exc:
        raise MelhorEnvioError(
            f'Falha de comunicação com o Melhor Envio: {exc}',
            status_code=502,
        ) from exc

    if response.status_code == 401 and TOKEN_FILE.exists():
        try:
            saved_token = json.loads(TOKEN_FILE.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError):
            saved_token = {}
        if isinstance(saved_token, dict) and saved_token.get('refresh_token'):
            _refresh_access_token(saved_token)
            try:
                response = requests.post(url, json=payload, headers=_headers(), timeout=30)
            except requests.RequestException as exc:
                raise MelhorEnvioError(
                    'Falha ao repetir a cotação após renovar o acesso ao Melhor Envio.',
                    status_code=502,
                ) from exc

    if response.status_code >= 400:
        details = {}
        try:
            details = response.json()
        except ValueError:
            details = {'raw': response.text[:500]}
        message = details.get('message') if isinstance(details, dict) else None
        raise MelhorEnvioError(
            message or f'Melhor Envio retornou erro HTTP {response.status_code}.',
            status_code=response.status_code,
            details=details,
        )

    return _normalizar_opcoes(response.json())


def _normalizar_opcoes(data):
    if not isinstance(data, list):
        return []

    opcoes = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get('error') or (item.get('message') and not item.get('name')):
            continue

        company = item.get('company') or {}
        opcoes.append({
            'id': item.get('id'),
            'name': item.get('name'),
            'company': company.get('name'),
            'company_picture': company.get('picture'),
            'price': item.get('custom_price') or item.get('price'),
            'currency': item.get('currency') or 'R$',
            'delivery_time': item.get('custom_delivery_time') or item.get('delivery_time'),
            'delivery_range': item.get('custom_delivery_range') or item.get('delivery_range'),
            'discount': item.get('discount'),
        })

    opcoes.sort(
        key=lambda o: float(str(o['price']).replace(',', '.')) if o.get('price') is not None else 999999
    )
    return opcoes
