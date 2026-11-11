"""Copia o banco antigo (SQLite) para o Supabase, criptografando tudo no caminho.

  python migrar_sqlite.py [caminho/castramovel.db] [pasta/uploads]

Padrão: instance/castramovel.db e instance/uploads. O banco de destino precisa estar vazio.
Depois de conferir, apague o .db e a pasta uploads antigos (estão em texto claro).
"""
import os
import sqlite3
import sys
import uuid
from datetime import datetime

from app import Agendamento, Animal, Documento, Tutor, Usuario, app, db
from seguranca import cifrar_bytes

ORIGEM_DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(app.instance_path, 'castramovel.db')
ORIGEM_UPLOADS = sys.argv[2] if len(sys.argv) > 2 else os.path.join(app.instance_path, 'uploads')


def main():
    if not os.path.isfile(ORIGEM_DB):
        sys.exit(f'Banco antigo não encontrado: {ORIGEM_DB}')
    origem = sqlite3.connect(ORIGEM_DB)
    origem.row_factory = sqlite3.Row

    with app.app_context():
        if Tutor.query.count() or Usuario.query.count():
            sys.exit('O banco de destino já tem dados. Migração cancelada para não duplicar.')

        for r in origem.execute('select * from usuario'):
            db.session.add(Usuario(id=r['id'], nome=r['nome'], senha_hash=r['senha_hash']))  # hash antigo é atualizado no 1º login

        for r in origem.execute('select * from tutor'):
            t = Tutor(id=r['id'], nome_completo=r['nome_completo'], telefone=r['telefone'],
                      endereco=r['endereco'], numero=r['numero'])
            t.definir_cpf(r['cpf'])
            db.session.add(t)
        db.session.flush()

        for r in origem.execute('select * from animal'):
            a = Animal(id=r['id'], nome=r['nome'], raca=r['raca'], sexo=r['sexo'], tutor_id=r['tutor_id'])
            a.definir_microchip(r['microchip'])
            db.session.add(a)
        db.session.flush()

        sem_arquivo = 0
        for r in origem.execute('select * from documento'):
            antigo = os.path.join(ORIGEM_UPLOADS, os.path.basename(r['caminho'].replace('\\', '/')))
            if not os.path.isfile(antigo):
                sem_arquivo += 1
                continue
            guardado = f'{uuid.uuid4().hex}.enc'
            with open(antigo, 'rb') as f, open(os.path.join(app.config['UPLOAD_FOLDER'], guardado), 'wb') as g:
                g.write(cifrar_bytes(f.read(), f'documento.arquivo:{guardado}'))
            db.session.add(Documento(id=r['id'], nome_arquivo=r['nome_arquivo'], caminho=guardado, tutor_id=r['tutor_id']))

        for r in origem.execute('select * from agendamento'):
            hora = r['hora'][:8] if len(r['hora']) >= 8 else r['hora'] + ':00'
            db.session.add(Agendamento(id=r['id'], data=datetime.strptime(r['data'][:10], '%Y-%m-%d').date(),
                                       hora=datetime.strptime(hora, '%H:%M:%S').time(), animal_id=r['animal_id']))
        db.session.commit()

        if db.engine.dialect.name == 'postgresql':  # ids foram copiados: acerta os contadores automáticos
            for tabela in ('usuario', 'tutor', 'animal', 'documento', 'agendamento'):
                db.session.execute(db.text(
                    f"select setval(pg_get_serial_sequence('public.{tabela}', 'id'), "
                    f"coalesce((select max(id) from public.{tabela}), 1))"))
            db.session.commit()

        print(f'Migrado: {Usuario.query.count()} usuário(s), {Tutor.query.count()} tutor(es), '
              f'{Animal.query.count()} animal(is), {Documento.query.count()} documento(s), '
              f'{Agendamento.query.count()} agendamento(s).')
        print('IMPORTANTE: os usuários migrados ainda não têm e-mail e não conseguem entrar. '
              'Para cada um rode: python usuarios.py email NOME')
        if sem_arquivo:
            print(f'Atenção: {sem_arquivo} documento(s) sem arquivo na pasta de uploads foram ignorados.')


if __name__ == '__main__':
    main()
