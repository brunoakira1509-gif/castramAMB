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

from app import AUTH, Animal, Tutor, Usuario, app, db, hash_senha, ler_animal, ler_tutor, usuario_por_email
from supabase_auth import EmailConfirmationRequired, InvalidCredentials


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

    def test_tutor_accepts_any_eleven_cpf_digits_with_mask(self):
        fields = {
            'nome': 'Tutor de teste',
            'telefone': '11999999999',
            'cpf': '111.111.111-11',
            'endereco': 'Rua de teste',
            'numero': '1',
        }

        data, error = ler_tutor(fields)

        self.assertIsNone(error)
        self.assertEqual(data['cpf'], '111.111.111-11')

    def test_tutor_still_requires_eleven_cpf_digits(self):
        fields = {
            'nome': 'Tutor de teste',
            'telefone': '11999999999',
            'cpf': '1234567890',
            'endereco': 'Rua de teste',
            'numero': '1',
        }

        _, error = ler_tutor(fields)

        self.assertEqual(error, 'Informe os 11 dígitos do CPF.')

    def test_animal_form_requires_a_supported_species(self):
        fields = {
            'nome': 'Mimi',
            'especie': 'gato',
            'raca': 'SRD',
            'sexo': 'femea',
            'microchip': '',
        }

        data, error = ler_animal(fields)

        self.assertIsNone(error)
        self.assertEqual(data['especie'], 'gato')
        fields['especie'] = ''
        _, error = ler_animal(fields)
        self.assertIsNotNone(error)

    def test_animal_species_and_searchable_tutor_picker_render(self):
        user = Usuario(nome='ana', senha_hash=hash_senha('senha forte 123'))
        tutor = Tutor(nome_completo='Maria de Souza', telefone='11999999999',
                      endereco='Rua de teste', numero='1')
        tutor.definir_cpf('12345678909')
        db.session.add_all([user, tutor])
        db.session.commit()
        with self.client.session_transaction() as session:
            session['usuario_id'] = user.id
            session['csrf'] = 'test-csrf'

        response = self.client.get('/cadastrar_animal')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'placeholder="Digite o nome ou CPF para buscar"', response.data)
        self.assertIn(b'<option value="cao">C\xc3\xa3o</option>', response.data)
        self.assertIn(b'<option value="gato">Gato</option>', response.data)
        self.assertNotIn(b'size="5"', response.data)

        response = self.client.post('/cadastrar_animal', data={
            'csrf_token': 'test-csrf',
            'tutor_id': str(tutor.id),
            'nome': 'Mimi',
            'especie': 'gato',
            'raca': 'SRD',
            'sexo': 'femea',
            'microchip': '',
        })

        self.assertEqual(response.status_code, 302)
        animal = Animal.query.one()
        self.assertEqual(animal.especie, 'gato')
        response = self.client.get(f'/animal/{animal.id}')
        self.assertIn(b'Esp\xc3\xa9cie: Gato', response.data)

    def test_empty_app_redirects_to_login(self):
        response = self.client.get('/')

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/login?proximo=/'))

    def test_first_confirmed_supabase_login_creates_local_profile(self):
        self._csrf()
        with patch.object(AUTH, 'sign_in', return_value={
            'access_token': 'token',
            'user': {
                'id': '67e55044-10b1-426f-9247-bb680e5fe0c8',
                'email': 'ana@example.com',
            },
        }) as sign_in:
            response = self.client.post('/login', data={
                'csrf_token': 'test-csrf',
                'email': 'ana@example.com',
                'senha': 'senha forte 123',
            })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/'))
        usuario = usuario_por_email('ana@example.com')
        self.assertIsNotNone(usuario)
        self.assertEqual(usuario.nome, 'supabase_67e5504410b1426f9247bb680e5fe0c8')
        sign_in.assert_called_once_with('ana@example.com', 'senha forte 123')
        response = self.client.get('/')
        self.assertIn(b'Conectado como ana@example.com', response.data)

    def test_unconfirmed_supabase_email_shows_confirmation_message(self):
        self._csrf()
        with patch.object(AUTH, 'sign_in', side_effect=EmailConfirmationRequired()):
            response = self.client.post('/login', data={
                'csrf_token': 'test-csrf',
                'email': 'ana@example.com',
                'senha': 'senha forte 123',
            })

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Confirme seu e-mail', response.data)
        self.assertNotIn(b'Desative a confirma', response.data)

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
