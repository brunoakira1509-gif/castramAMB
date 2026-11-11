import base64
import os
import secrets
import unittest
from unittest.mock import patch


def _key():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


os.environ.update(
    CASTRAMOVEL_DATA_KEY=_key(),
    CASTRAMOVEL_INDEX_KEY=_key(),
    CASTRAMOVEL_PEPPER=_key(),
    CASTRAMOVEL_SECRET_KEY=secrets.token_hex(32),
    DATABASE_URL='sqlite:///:memory:',
    SUPABASE_URL='https://project.supabase.co',
    SUPABASE_PUBLISHABLE_KEY='sb_publishable_test',
)

from app import AUTH, Usuario, app, db, hash_senha
from supabase_auth import InvalidCredentials


class AppAuthTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.context = app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def _csrf(self):
        with self.client.session_transaction() as session:
            session['csrf'] = 'test-csrf'

    def test_first_access_creates_supabase_account_without_email_code(self):
        self._csrf()
        with patch.object(AUTH, 'sign_up_or_sign_in') as sign_up:
            response = self.client.post('/primeiro_acesso', data={
                'csrf_token': 'test-csrf',
                'usuario': 'ana',
                'email': 'ana@example.com',
                'senha': 'senha forte 123',
                'confirmacao': 'senha forte 123',
            })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/'))
        self.assertIsNotNone(Usuario.query.filter_by(nome='ana').first())
        sign_up.assert_called_once_with('ana@example.com', 'senha forte 123')

    def test_legacy_password_is_migrated_on_first_email_login(self):
        usuario = Usuario(nome='ana', senha_hash=hash_senha('senha forte 123'))
        usuario.definir_email('ana@example.com')
        db.session.add(usuario)
        db.session.commit()
        self._csrf()

        with patch.object(AUTH, 'sign_in', side_effect=InvalidCredentials()), \
                patch.object(AUTH, 'sign_up_or_sign_in') as sign_up:
            response = self.client.post('/login', data={
                'csrf_token': 'test-csrf',
                'email': 'ana@example.com',
                'senha': 'senha forte 123',
            })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/'))
        sign_up.assert_called_once_with('ana@example.com', 'senha forte 123')


if __name__ == '__main__':
    unittest.main(verbosity=2)
