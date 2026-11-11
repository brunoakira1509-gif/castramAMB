"""Gerencia usuários pelo terminal.

  python usuarios.py listar
  python usuarios.py criar NOME
  python usuarios.py senha NOME      (redefine a senha)
  python usuarios.py remover NOME
"""
import getpass
import sys

from werkzeug.security import generate_password_hash

from app import Usuario, app, db


def pedir_senha():
    senha = getpass.getpass('Senha (mínimo 8 caracteres): ')
    if len(senha) < 8 or senha != getpass.getpass('Repita a senha: '):
        sys.exit('Senha curta demais ou diferente da confirmação.')
    return generate_password_hash(senha)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('listar', 'criar', 'senha', 'remover'):
        sys.exit(__doc__)
    comando = sys.argv[1]
    with app.app_context():
        if comando == 'listar':
            for u in Usuario.query.order_by(Usuario.nome).all():
                print(u.nome)
            return
        if len(sys.argv) < 3:
            sys.exit('Informe o nome do usuário.')
        nome = sys.argv[2].strip().lower()
        usuario = Usuario.query.filter_by(nome=nome).first()
        if comando == 'criar':
            if usuario:
                sys.exit('Esse usuário já existe.')
            db.session.add(Usuario(nome=nome, senha_hash=pedir_senha()))
        elif not usuario:
            sys.exit('Usuário não encontrado.')
        elif comando == 'senha':
            usuario.senha_hash = pedir_senha()
        else:
            db.session.delete(usuario)
        db.session.commit()
        print('Pronto.')


if __name__ == '__main__':
    main()
