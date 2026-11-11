"""Client for the Supabase Auth password endpoints."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import ConfigFaltando, segredo


class SupabaseAuthError(RuntimeError):
    pass


class InvalidCredentials(SupabaseAuthError):
    pass


class AccountAlreadyExists(SupabaseAuthError):
    pass


class EmailConfirmationRequired(SupabaseAuthError):
    pass


class AuthUnavailable(SupabaseAuthError):
    pass


class SupabaseAuth:
    def __init__(self, project_url=None, api_key=None):
        self.project_url = (project_url or segredo('SUPABASE_URL')).rstrip('/')
        if not self.project_url.startswith('https://'):
            raise RuntimeError('SUPABASE_URL precisa começar com https://.')
        self.api_key = api_key or self._read_api_key()

    @staticmethod
    def _read_api_key():
        for name in ('SUPABASE_PUBLISHABLE_KEY', 'SUPABASE_ANON_KEY'):
            try:
                return segredo(name)
            except ConfigFaltando:
                pass
        raise ConfigFaltando(
            'Variável SUPABASE_PUBLISHABLE_KEY não configurada. '
            'Adicione a chave publicável (ou anon) do projeto Supabase.')

    def _request(self, method, path, payload, access_token=None):
        body = json.dumps(payload).encode('utf-8')
        headers = {'apikey': self.api_key, 'Content-Type': 'application/json'}
        if access_token:
            headers['Authorization'] = f'Bearer {access_token}'
        req = Request(f'{self.project_url}/auth/v1/{path}', data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=10) as response:
                raw = response.read()
        except HTTPError as exc:
            try:
                error = json.loads(exc.read().decode('utf-8'))
            except (UnicodeDecodeError, ValueError):
                error = {}
            if not isinstance(error, dict):
                error = {}
            code = error.get('code') or error.get('error_code')
            message = error.get('message') or error.get('msg')
            texto = str(message or '').casefold()
            if code == 'invalid_credentials' or 'invalid login credentials' in texto:
                raise InvalidCredentials('E-mail ou senha incorretos.') from exc
            if code in ('user_already_exists', 'email_exists') or 'already registered' in texto:
                raise AccountAlreadyExists('Já existe uma conta Supabase Auth para este e-mail.') from exc
            if code == 'email_not_confirmed' or 'email not confirmed' in texto:
                raise EmailConfirmationRequired(
                    'Confirme o e-mail pelo link enviado pelo Supabase antes de entrar.') from exc
            raise SupabaseAuthError(f'Supabase Auth respondeu com HTTP {exc.code}.') from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AuthUnavailable('Não foi possível conectar ao Supabase Auth.') from exc

        try:
            data = json.loads(raw.decode('utf-8')) if raw else {}
        except (UnicodeDecodeError, ValueError) as exc:
            raise SupabaseAuthError('Supabase Auth retornou uma resposta inválida.') from exc
        if not isinstance(data, dict):
            raise SupabaseAuthError('Supabase Auth retornou uma resposta inválida.')
        return data

    def sign_in(self, email, password):
        data = self._request('POST', 'token?grant_type=password',
                             {'email': email, 'password': password})
        user = data.get('user')
        if not data.get('access_token') or not isinstance(user, dict) or not user.get('email'):
            raise SupabaseAuthError('Supabase Auth não retornou uma sessão válida.')
        return data

    def sign_up(self, email, password):
        data = self._request('POST', 'signup', {'email': email, 'password': password})
        user = data.get('user')
        if not data.get('access_token') or not isinstance(user, dict) or not user.get('email'):
            raise EmailConfirmationRequired(
                'Confirme o e-mail pelo link enviado pelo Supabase antes de entrar.')
        return data

    def sign_up_or_sign_in(self, email, password):
        try:
            return self.sign_up(email, password)
        except AccountAlreadyExists:
            return self.sign_in(email, password)

    def update_password(self, access_token, password):
        return self._request('PUT', 'user', {'password': password}, access_token)
