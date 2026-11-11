"""Gerencia usuários pelo terminal.

  python usuarios.py listar
  python usuarios.py criar NOME
  python usuarios.py email NOME      (define/troca o e-mail que recebe o código de login)
  python usuarios.py senha NOME      (redefine a senha)
  python usuarios.py remover NOME
"""
import getpass
import sys

from app import SENHA_MIN, Usuario, app, db, email_valido, mascarar_email
from seguranca import hash_senha


def pedir_senha():
    senha = getpass.getpass(f'Senha (mínimo {SENHA_MIN} caracteres): ')
    if len(senha) < SENHA_MIN or senha != getpass.getpass('Repita a senha: '):
        sys.exit('Senha curta demais ou diferente da confirmação.')
    return hash_senha(senha)


def pedir_email():
    email = input('E-mail para receber o código de login: ').strip()
    if not email_valido(email):
        sys.exit('E-mail inválido.')
    return email


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('listar', 'criar', 'senha', 'email', 'remover'):
        sys.exit(__doc__)
    comando = sys.argv[1]
    with app.app_context():
        if comando == 'listar':
            for u in Usuario.query.order_by(Usuario.nome).all():
                print(u.nome, mascarar_email(u.email) if u.email else '(sem e-mail: não consegue entrar)')
            return
        if len(sys.argv) < 3:
            sys.exit('Informe o nome do usuário.')
        nome = sys.argv[2].strip().lower()
        usuario = Usuario.query.filter_by(nome=nome).first()
        if comando == 'criar':
            if usuario:
                sys.exit('Esse usuário já existe.')
            novo = Usuario(nome=nome, senha_hash=pedir_senha())
            novo.definir_email(pedir_email())
            db.session.add(novo)
        elif not usuario:
            sys.exit('Usuário não encontrado.')
        elif comando == 'senha':
            usuario.senha_hash = pedir_senha()
        elif comando == 'email':
            usuario.definir_email(pedir_email())
        else:
            db.session.delete(usuario)
        db.session.commit()
        print('Pronto.')


if __name__ == '__main__':
    main()
