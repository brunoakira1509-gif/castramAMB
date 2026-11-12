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

from datetime import time, timedelta

from agenda_regras import hoje
from app import (AUTH, Agendamento, Animal, Documento, Tutor, Usuario, app, db, hash_senha, ler_animal, ler_tutor,
                 usuario_por_email)
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

    def _login(self, perfil='admin'):
        user = Usuario(nome='ana', senha_hash=hash_senha('senha forte 123'), perfil=perfil)
        db.session.add(user)
        db.session.commit()
        with self.client.session_transaction() as session:
            session['usuario_id'] = user.id
            session['csrf'] = 'test-csrf'

    def _tutor(self, nome='Maria de Souza', cpf='12345678909'):
        tutor = Tutor(nome_completo=nome, telefone='11999999999', endereco='Rua de teste', numero='1')
        tutor.definir_cpf(cpf)
        db.session.add(tutor)
        db.session.commit()
        return tutor

    def _animal(self, tutor, nome, especie, sexo):
        animal = Animal(nome=nome, especie=especie, raca='SRD', sexo=sexo, tutor_id=tutor.id)
        db.session.add(animal)
        db.session.commit()
        return animal

    def _proximo_dia_util(self):
        dia = hoje() + timedelta(days=1)
        while dia.weekday() >= 5:
            dia += timedelta(days=1)
        return dia

    def _agendar(self, animal, dia, hora):
        return self.client.post('/agendar', data={'csrf_token': 'test-csrf', 'animal_id': str(animal.id),
                                                  'data': dia.isoformat(), 'hora': hora})

    def test_animal_registration_first_picks_tutor_then_shows_form(self):
        tutor = self._tutor()
        self._login()

        response = self.client.get('/cadastrar_animal')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'placeholder="Digite o nome ou o CPF do tutor"', response.data)
        self.assertIn(b'Maria de Souza', response.data)
        self.assertNotIn(b'name="especie"', response.data)

        response = self.client.get(f'/cadastrar_animal?tutor_id={tutor.id}')
        self.assertIn(b'name="especie" id="especie-cao" value="cao"', response.data)
        self.assertIn(b'name="especie" id="especie-gato" value="gato"', response.data)

        response = self.client.post('/cadastrar_animal', data={
            'csrf_token': 'test-csrf', 'tutor_id': str(tutor.id), 'nome': 'Mimi',
            'especie': 'gato', 'raca': 'SRD', 'sexo': 'femea', 'microchip': '',
        })
        self.assertEqual(response.status_code, 302)
        animal = Animal.query.one()
        self.assertEqual(animal.especie, 'gato')
        response = self.client.get(f'/animal/{animal.id}')
        self.assertIn(b'Esp\xc3\xa9cie: Gato', response.data)

    def test_tutor_search_api_filters_by_name_and_cpf(self):
        self._tutor('Maria de Souza', '12345678909')
        self._tutor('Joao Pereira', '98765432100')
        self._login()
        nomes = [t['nome'] for t in self.client.get('/api/tutores?q=joao').get_json()['tutores']]
        self.assertEqual(nomes, ['Joao Pereira'])
        nomes = [t['nome'] for t in self.client.get('/api/tutores?q=123.456').get_json()['tutores']]
        self.assertEqual(nomes, ['Maria de Souza'])
        self.assertEqual(len(self.client.get('/api/tutores').get_json()['tutores']), 2)

    def test_schedule_follows_fixed_times_and_vacancies(self):
        tutor = self._tutor()
        gata1, gata2, gata3 = (self._animal(tutor, f'Gata{i}', 'gato', 'femea') for i in range(3))
        cadela = self._animal(tutor, 'Luna', 'cao', 'femea')
        cao = self._animal(tutor, 'Rex', 'cao', 'macho')
        gato = self._animal(tutor, 'Tom', 'gato', 'macho')
        self._login()
        dia = self._proximo_dia_util()

        self._agendar(gata1, dia, '08:00')
        self._agendar(gata2, dia, '08:00')
        self._agendar(gata3, dia, '08:00')  # terceira gata: não cabe
        self.assertEqual(Agendamento.query.filter_by(hora=time(8, 0)).count(), 2)

        self._agendar(cadela, dia, '08:00')  # cadela às 8:00: horário só de gatas
        self.assertEqual(Agendamento.query.filter_by(animal_id=cadela.id).count(), 0)

        self._agendar(cao, dia, '10:00')  # fora da grade
        self.assertEqual(Agendamento.query.filter_by(animal_id=cao.id).count(), 0)

        self._agendar(gato, dia, '08:30')
        self.assertEqual(Agendamento.query.filter_by(animal_id=gato.id).count(), 1)

        self._agendar(cadela, dia, '14:30')
        self.assertEqual(Agendamento.query.filter_by(animal_id=cadela.id).count(), 1)

    def test_animal_cannot_have_two_future_bookings_and_cancel_frees_the_spot(self):
        tutor = self._tutor()
        cadela = self._animal(tutor, 'Luna', 'cao', 'femea')
        outra = self._animal(tutor, 'Bela', 'cao', 'femea')
        self._login()
        dia = self._proximo_dia_util()

        self._agendar(cadela, dia, '09:30')
        self._agendar(cadela, dia, '13:00')  # a mesma cadela de novo: recusado
        self.assertEqual(Agendamento.query.count(), 1)
        self._agendar(outra, dia, '09:30')  # horário de 1 vaga já ocupado
        self.assertEqual(Agendamento.query.count(), 1)

        agendamento = Agendamento.query.one()
        response = self.client.post(f'/agendamentos/{agendamento.id}/cancelar', data={'csrf_token': 'test-csrf'})
        self.assertEqual(response.status_code, 302)
        self._agendar(outra, dia, '09:30')
        self.assertEqual(Agendamento.query.one().animal_id, outra.id)

    def test_weekend_and_past_dates_are_refused(self):
        tutor = self._tutor()
        cadela = self._animal(tutor, 'Luna', 'cao', 'femea')
        self._login()
        sabado = hoje() + timedelta(days=(5 - hoje().weekday()) % 7 or 7)
        self._agendar(cadela, sabado, '09:30')
        self._agendar(cadela, hoje() - timedelta(days=1), '09:30')
        self.assertEqual(Agendamento.query.count(), 0)

    def test_home_shows_only_today_and_calendar_shows_other_days(self):
        tutor = self._tutor('Maria de Souza')
        gata = self._animal(tutor, 'Mimi', 'gato', 'femea')
        cadela = self._animal(tutor, 'Luna', 'cao', 'femea')
        db.session.add_all([Agendamento(data=hoje(), hora=time(8, 0), animal_id=gata.id),
                            Agendamento(data=hoje() + timedelta(days=3), hora=time(9, 30), animal_id=cadela.id)])
        db.session.commit()
        self._login()

        inicio = self.client.get('/').data.decode()
        if hoje().weekday() < 5:
            self.assertIn('Mimi', inicio)
        self.assertNotIn('Luna', inicio)

        futuro = hoje() + timedelta(days=3)
        pagina = self.client.get(f'/calendario?mes={futuro:%Y-%m}&dia={futuro.isoformat()}')
        self.assertEqual(pagina.status_code, 200)
        texto = pagina.data.decode()
        if futuro.weekday() < 5:
            self.assertIn('Luna', texto)
            self.assertIn(f'/animal/{cadela.id}', texto)
            self.assertIn(f'/tutor/{tutor.id}', texto)

    def test_vet_user_has_limited_read_only_access(self):
        tutor = self._tutor()
        animal = self._animal(tutor, 'Mimi', 'gato', 'femea')
        self._login('veterinario')
        resposta = self.client.get('/')
        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(resposta.headers['Location'].endswith('/atendimento'))
        # administração fica fechada para o veterinário
        for caminho in ('/agendamentos', '/procurar_tutor', '/procurar_animal', '/cadastrar_tutor',
                        '/cadastrar_animal', f'/editar_animal/{animal.id}', '/api/tutores', '/relatorios',
                        '/gerar_csv_animalltag', '/gerar_excel_dia'):
            r = self.client.get(caminho)
            self.assertEqual(r.status_code, 302, caminho)
            self.assertTrue(r.headers['Location'].endswith('/atendimento'), caminho)
        for caminho in ('/agendar', f'/tutor/{tutor.id}', f'/animal/{animal.id}', '/cadastrar_tutor'):
            self.assertEqual(self.client.post(caminho, data={'csrf_token': 'test-csrf'}).status_code, 403, caminho)
        # mas pode ler calendário, atendimento e as fichas
        for caminho in ('/atendimento', '/calendario', f'/tutor/{tutor.id}', f'/animal/{animal.id}'):
            self.assertEqual(self.client.get(caminho).status_code, 200, caminho)
        pagina = self.client.get('/atendimento').data.decode()
        self.assertNotIn('Procurar tutor', pagina)
        self.assertNotIn('Relatórios', pagina)

    def test_vet_can_only_edit_the_microchip(self):
        tutor = self._tutor()
        animal = self._animal(tutor, 'Mimi', 'gato', 'femea')
        outro = self._animal(tutor, 'Rex', 'cao', 'macho')
        outro.definir_microchip('985000000000002')
        db.session.commit()
        self._login('veterinario')

        pagina = self.client.get(f'/animal/{animal.id}').data.decode()
        self.assertIn(f'/animal/{animal.id}/microchip', pagina)
        self.assertNotIn('name="nome"', pagina)  # os outros dados são só leitura
        self.assertNotIn('name="raca"', pagina)
        self.assertNotIn('Agendar castração', pagina)
        self.assertIn('data-scan-target="microchip-num"', pagina)  # leitor de código de barras (aparece só no celular)
        self.assertIn('camera=(self)', self.client.get(f'/animal/{animal.id}').headers['Permissions-Policy'])
        ficha_tutor = self.client.get(f'/tutor/{tutor.id}').data.decode()
        self.assertIn('Maria de Souza', ficha_tutor)
        self.assertNotIn('name="nome"', ficha_tutor)
        self.assertNotIn('Documentos', ficha_tutor)

        def salvar(valor, extra=None):
            dados = {'csrf_token': 'test-csrf', 'microchip': valor}
            dados.update(extra or {})
            return self.client.post(f'/animal/{animal.id}/microchip', data=dados)

        self.assertEqual(salvar('985 112 345 678 901', {'nome': 'Hackeado', 'sexo': 'macho'}).status_code, 302)
        db.session.refresh(animal)
        self.assertEqual(animal.microchip, '985112345678901')
        self.assertEqual((animal.nome, animal.sexo), ('Mimi', 'femea'))  # nada além do microchip muda
        salvar('985000000000002')  # já usado por outro animal
        db.session.refresh(animal)
        self.assertEqual(animal.microchip, '985112345678901')
        salvar('9' * 21)  # grande demais
        db.session.refresh(animal)
        self.assertEqual(animal.microchip, '985112345678901')
        salvar('')
        db.session.refresh(animal)
        self.assertIsNone(animal.microchip)

    def test_vet_calendar_is_read_only(self):
        tutor = self._tutor()
        gata = self._animal(tutor, 'Mimi', 'gato', 'femea')
        dia = self._proximo_dia_util()
        db.session.add(Agendamento(data=dia, hora=time(8, 0), animal_id=gata.id))
        db.session.commit()
        self._login('veterinario')
        pagina = self.client.get(f'/calendario?mes={dia:%Y-%m}&dia={dia.isoformat()}').data.decode()
        self.assertIn('Mimi', pagina)
        self.assertNotIn('Cancelar', pagina)
        self.assertNotIn('Novo agendamento', pagina)
        self.assertNotIn('Agendar', pagina)
        self.assertEqual(self.client.post(f'/agendamentos/{Agendamento.query.one().id}/cancelar',
                                          data={'csrf_token': 'test-csrf'}).status_code, 403)
        self.assertEqual(Agendamento.query.count(), 1)

    def test_admin_interface_has_no_attendance_tab_and_can_switch_profile(self):
        self._login('admin')
        pagina = self.client.get('/').data.decode()
        self.assertNotIn('>Atendimento<', pagina)
        self.assertNotIn('/atendimento', pagina)
        self.assertIn('Trocar para Veterinário', pagina)
        r = self.client.get('/atendimento')  # a Administração não usa mais essa tela
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers['Location'].endswith('/'))

        r = self.client.post('/trocar_perfil', data={'csrf_token': 'test-csrf', 'modo': 'veterinario'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers['Location'].endswith('/atendimento'))
        pagina = self.client.get('/atendimento').data.decode()
        self.assertIn('Trocar para Administração', pagina)
        self.assertIn('Perfil: <strong>Veterinário</strong>', pagina)
        # no modo Veterinário o admin também fica limitado
        self.assertEqual(self.client.get('/relatorios').status_code, 302)
        self.assertEqual(self.client.post('/agendar', data={'csrf_token': 'test-csrf'}).status_code, 403)

        r = self.client.post('/trocar_perfil', data={'csrf_token': 'test-csrf', 'modo': 'admin'})
        self.assertTrue(r.headers['Location'].endswith('/'))
        self.assertEqual(self.client.get('/relatorios').status_code, 200)
        self.assertEqual(self.client.post('/trocar_perfil', data={'csrf_token': 'test-csrf', 'modo': 'x'}).status_code, 403)

    def test_vet_account_cannot_switch_to_administration(self):
        self._login('veterinario')
        pagina = self.client.get('/atendimento').data.decode()
        self.assertNotIn('Trocar para', pagina)
        self.assertEqual(self.client.post('/trocar_perfil', data={'csrf_token': 'test-csrf', 'modo': 'admin'}).status_code, 403)
        with self.client.session_transaction() as sessao:
            sessao['modo'] = 'admin'  # mesmo forçando a sessão, o servidor ignora
        self.assertEqual(self.client.get('/relatorios').status_code, 302)

    def test_legacy_campo_profile_behaves_as_vet(self):
        self._login('campo')
        self.assertEqual(self.client.get('/relatorios').status_code, 302)
        self.assertEqual(self.client.get('/atendimento').status_code, 200)

    def test_attendance_shows_species_tutor_and_marks_presence(self):
        tutor = self._tutor('Maria de Souza')
        gata = self._animal(tutor, 'Mimi', 'gato', 'femea')
        ag = Agendamento(data=hoje(), hora=time(8, 0), animal_id=gata.id)
        db.session.add(ag)
        db.session.commit()
        self._login('veterinario')

        pagina = self.client.get('/atendimento').data.decode()
        self.assertIn('Mimi', pagina)
        self.assertIn('Gato', pagina)
        self.assertIn('Maria de Souza', pagina)
        self.assertIn('tel:11999999999', pagina)
        self.assertNotIn('12345678909', pagina)  # o CPF não aparece na tela de atendimento

        def marcar(valor):
            return self.client.post(f'/atendimento/{ag.id}/presenca',
                                    data={'csrf_token': 'test-csrf', 'valor': valor, 'voltar': '/atendimento'})
        self.assertEqual(marcar('presente').status_code, 302)
        db.session.refresh(ag)
        self.assertIs(ag.presente, True)
        marcar('faltou')
        db.session.refresh(ag)
        self.assertIs(ag.presente, False)
        marcar('limpar')
        db.session.refresh(ag)
        self.assertIsNone(ag.presente)
        self.assertEqual(marcar('qualquer coisa').status_code, 400)

    def test_presence_cannot_be_marked_for_a_future_day(self):
        tutor = self._tutor()
        gata = self._animal(tutor, 'Mimi', 'gato', 'femea')
        ag = Agendamento(data=hoje() + timedelta(days=2), hora=time(8, 0), animal_id=gata.id)
        db.session.add(ag)
        db.session.commit()
        self._login('veterinario')
        self.client.post(f'/atendimento/{ag.id}/presenca',
                         data={'csrf_token': 'test-csrf', 'valor': 'presente', 'voltar': '/atendimento'})
        db.session.refresh(ag)
        self.assertIsNone(ag.presente)

    def test_animalltag_csv_exports_tutor_and_microchip(self):
        tutor = self._tutor('Maria de Souza', '12345678909')
        com_chip = self._animal(tutor, 'Mimi', 'gato', 'femea')
        com_chip.definir_microchip('985 112 345 678 901')
        sem_chip = self._animal(tutor, 'Rex', 'cao', 'macho')
        faltou = self._animal(tutor, 'Luna', 'cao', 'femea')
        faltou.definir_microchip('985000000000002')
        db.session.add_all([
            Agendamento(data=hoje(), hora=time(8, 0), animal_id=com_chip.id, presente=True),
            Agendamento(data=hoje(), hora=time(8, 30), animal_id=sem_chip.id, presente=True),
            Agendamento(data=hoje(), hora=time(9, 30), animal_id=faltou.id, presente=False)])
        db.session.commit()
        self._login()
        consulta = f'de={hoje().isoformat()}&ate={hoje().isoformat()}'

        resposta = self.client.get(f'/gerar_csv_animalltag?{consulta}&presentes=1')
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('text/csv', resposta.headers['Content-Type'])
        linhas = resposta.data.decode('utf-8-sig').strip().split('\r\n')
        self.assertEqual(len(linhas), 2)  # cabeçalho + só o animal presente e com microchip
        self.assertIn('985112345678901', linhas[1])
        self.assertIn('Maria de Souza', linhas[1])
        self.assertIn('12345678909', linhas[1])

        todos = self.client.get(f'/gerar_csv_animalltag?{consulta}').data.decode('utf-8-sig').strip().split('\r\n')
        self.assertEqual(len(todos), 3)  # Mimi e Luna (Rex não tem microchip)

        vazio = self.client.get('/gerar_csv_animalltag?de=2000-01-01&ate=2000-01-02')
        self.assertEqual(vazio.status_code, 302)
        invalido = self.client.get('/gerar_csv_animalltag?de=abc&ate=def')
        self.assertEqual(invalido.status_code, 302)

    def test_document_is_stored_encrypted_and_viewable(self):
        import io
        tutor = self._tutor()
        self._login()
        conteudo = b'%PDF-1.4 conteudo secreto'
        response = self.client.post(f'/tutor/{tutor.id}', data={
            'csrf_token': 'test-csrf', 'nome': tutor.nome_completo, 'telefone': '11999999999',
            'cpf': '12345678909', 'endereco': 'Rua de teste', 'numero': '1',
            'documentos': (io.BytesIO(conteudo), 'rg.pdf')}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200)
        doc = Documento.query.one()
        self.assertNotIn(b'conteudo secreto', bytes(doc.conteudo))

        pagina = self.client.get(f'/documento/{doc.id}/ver')
        self.assertEqual(pagina.status_code, 200)
        self.assertIn(b'<iframe', pagina.data)
        arquivo = self.client.get(f'/documento/{doc.id}')
        self.assertEqual(arquivo.data, conteudo)
        self.assertEqual(arquivo.headers['X-Frame-Options'], 'SAMEORIGIN')
        baixar = self.client.get(f'/documento/{doc.id}?baixar=1')
        self.assertIn('attachment', baixar.headers['Content-Disposition'])
        self.assertEqual(self.client.get('/').headers['X-Frame-Options'], 'DENY')

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
        self.assertEqual(usuario.perfil, 'veterinario')  # contas novas começam com o menor acesso
        sign_in.assert_called_once_with('ana@example.com', 'senha forte 123')
        response = self.client.get('/', follow_redirects=True)  # conta nova (veterinário) cai na tela Atendimento
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
