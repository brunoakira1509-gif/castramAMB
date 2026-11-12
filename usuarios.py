"""Gerencia usuários pelo terminal.

  python usuarios.py listar
  python usuarios.py criar NOME [veterinario]   (sem "veterinario" a conta é administradora)
  python usuarios.py perfil NOME_OU_EMAIL admin|veterinario
  python usuarios.py senha NOME | email NOME | remover NOME

Perfis: admin usa a Administração e o Veterinário (e troca entre eles); veterinario usa só a interface Veterinário.
"""
import getpass
import sys

from app import (SENHA_MIN, Usuario, app, atualizar_email_usuario, atualizar_senha_usuario,
                 criar_ou_entrar_no_supabase, db, email_valido, mascarar_email, mensagem_de_erro_auth,
                 usuario_por_email, validar_senha)
from sqlalchemy.exc import IntegrityError
from seguranca import hash_senha
from supabase_auth import SupabaseAuthError


def pedir_senha():
    senha = getpass.getpass(f'Senha (mínimo {SENHA_MIN} caracteres): ')
    erro = validar_senha(senha, getpass.getpass('Repita a senha: '))
    if erro:
        sys.exit(erro)
    return senha


def pedir_email():
    email = input('E-mail de acesso: ').strip().lower()
    if not email_valido(email):
        sys.exit('E-mail inválido.')
    return email


def autenticar_nova_conta(email, senha):
    try:
        criar_ou_entrar_no_supabase(email, senha)
    except SupabaseAuthError as exc:
        sys.exit(mensagem_de_erro_auth(exc))


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('listar', 'criar', 'senha', 'email', 'remover', 'perfil'):
        sys.exit(__doc__)
    comando = sys.argv[1]
    with app.app_context():
        if comando == 'listar':
            for u in Usuario.query.order_by(Usuario.nome).all():
                print(u.nome, f'[{u.perfil}]', mascarar_email(u.email) if u.email else '(sem e-mail: não consegue entrar)')
            return
        if len(sys.argv) < 3:
            sys.exit('Informe o nome do usuário.')
        nome = sys.argv[2].strip().lower()
        usuario = Usuario.query.filter_by(nome=nome).first()
        if comando == 'perfil':
            novo_perfil = sys.argv[3].strip().lower() if len(sys.argv) > 3 else ''
            novo_perfil = 'veterinario' if novo_perfil == 'campo' else novo_perfil  # 'campo' é o nome antigo
            if novo_perfil not in ('admin', 'veterinario'):
                sys.exit('Informe o perfil: admin ou veterinario.')
            usuario = usuario or usuario_por_email(nome)  # aceita o nome de login ou o e-mail
            if not usuario:
                sys.exit('Usuário não encontrado (o usuário precisa ter entrado ao menos uma vez).')
            usuario.perfil = novo_perfil
            db.session.commit()
            print(f'Pronto. {usuario.nome} agora é {novo_perfil}.')
            return
        if comando == 'criar':
            if usuario:
                sys.exit('Esse usuário já existe.')
            senha = pedir_senha()
            email = pedir_email()
            if usuario_por_email(email):
                sys.exit('Esse e-mail já está associado a um usuário.')
            autenticar_nova_conta(email, senha)
            perfil = 'veterinario' if len(sys.argv) > 3 and sys.argv[3].strip().lower() in ('veterinario', 'campo') else 'admin'
            novo = Usuario(nome=nome, senha_hash=hash_senha(senha), perfil=perfil)
            novo.definir_email(email)
            db.session.add(novo)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                sys.exit('Não foi possível criar o usuário. Confira se o nome já está em uso.')
            print('Pronto.')
            return
        elif not usuario:
            sys.exit('Usuário não encontrado.')
        elif comando == 'senha':
            atual = getpass.getpass('Senha atual: ')
            nova = pedir_senha()
            try:
                atualizar_senha_usuario(usuario, atual, nova)
            except SupabaseAuthError as exc:
                sys.exit(mensagem_de_erro_auth(exc))
            print('Pronto.')
            return
        elif comando == 'email':
            try:
                atualizar_email_usuario(usuario, pedir_email())
            except SupabaseAuthError as exc:
                sys.exit(mensagem_de_erro_auth(exc))
        else:
            db.session.delete(usuario)
        db.session.commit()
        print('Pronto.')
        if comando == 'remover':
            print('A conta no Supabase Auth permanece; sem o usuário local, ela não acessa o sistema.')


if __name__ == '__main__':
    main()
