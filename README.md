# CastraMóvel - Sistema de Organização

Este é um sistema web para organizar o serviço móvel de castração de animais (Cães e Gatos).

## Funcionalidades

- Cadastro de Tutores (donos dos animais) com informações pessoais e anexos de documentos.
- Cadastro de Animais vinculados aos tutores.
- Busca por Tutores e Animais.
- Agendamento de castrações (segunda a sexta-feira).
- Geração de relatórios em Excel para agendas mensais ou diárias.

## Tecnologias

- Backend: Flask (Python)
- Banco de Dados: PostgreSQL no Supabase (dados pessoais criptografados pelo app)
- Frontend: HTML, CSS, JavaScript básico

## Instalação

1. Instale as dependências: `pip install -r requirements.txt`
2. Crie o `.env` com as chaves: `python gerar_chaves.py`, e preencha no `.env` os dados de SMTP (o e-mail que envia o código de login; no Gmail use uma "senha de app")
3. No Supabase: **SQL Editor > New query**, cole o conteúdo de `supabase_schema.sql` e clique em **Run**
   (cria as tabelas e trava o acesso pelas chaves públicas). Confira que todas as linhas mostram `rls_ativo = true`.
4. No Supabase: botão **Connect** > **Session pooler**, copie a string de conexão, troque `[YOUR-PASSWORD]`
   pela senha do banco e cole em `DATABASE_URL` no `.env`.
5. Tinha dados no sistema antigo (SQLite)? Rode `python migrar_sqlite.py`. Depois de conferir, apague
   `instance/castramovel.db` e `instance/uploads` antigos (estão em texto claro).
6. Inicie (`iniciar_servidor.bat` ou `python serve.py`) e acesse http://localhost:5000/ . Se não houver usuários,
   o sistema pede para criar o primeiro: faça isso logo após subir o servidor.

## Segurança

- **Segredos fora do código**: tudo no `.env` (ignorado pelo git). O navegador nunca recebe chave, senha do banco ou URL do banco.
- **Dados criptografados** (AES-256-GCM) antes de ir ao banco: nome, telefone, CPF, endereço, número do tutor; nome, raça, sexo e microchip do animal; nome dos documentos. Os arquivos anexados também são cifrados no disco.
  Ficam em claro apenas ids, data/hora dos agendamentos e o nome de login.
- **Relatórios Excel**: o servidor descriptografa em memória só para montar a planilha; nada em claro vai para o disco.
- **Verificação por e-mail**: depois da senha, um código de 6 dígitos (válido por 10 min, uso único, 5 tentativas) é enviado ao e-mail do usuário. Só o hash do código é guardado.
- **Senhas**: scrypt com salt individual + pepper secreto do `.env`. Mínimo de 10 caracteres.
- **Injection**: todas as consultas são parametrizadas (SQLAlchemy), entradas são validadas, o HTML é escapado e as planilhas
  neutralizam fórmulas (`=`, `+`, `-`, `@`).
- **Navegador**: proteção CSRF, cookie HttpOnly, política CSP (bloqueia script/estilo injetado), cabeçalhos de segurança, sem cache.
- **Supabase**: RLS ligado e sem policies. As chaves públicas (publishable/anon) não leem nem gravam nada.
  O app conecta direto no Postgres com a senha do banco.
- **Guarde o `.env` em local seguro.** Sem `CASTRAMOVEL_DATA_KEY` os dados do banco não podem ser recuperados (nem por nós, nem pelo Supabase).
- Se o sistema for acessado por HTTPS, coloque `CASTRAMOVEL_HTTPS=1` no `.env`.

## Uso em rede local (LAN)

- Um PC é o servidor: só ele guarda a pasta `instance/uploads/` (arquivos cifrados) e o `.env`; o banco fica no Supabase.
- No servidor, execute `liberar_firewall.bat` como administrador (uma vez). Ele libera a porta 5000 apenas para redes privadas.
- Ao iniciar, `serve.py` mostra o endereço da rede, por exemplo `http://192.168.0.15:5000`. Abra esse endereço nos outros PCs.
- Reserve o IP do servidor no roteador para o endereço não mudar.
- Não faça redirecionamento de portas no roteador: o sistema deve ficar só na rede local.
- Faça backup de `instance/uploads/` e do `.env` com frequência.

## Usuários

- Alterar a própria senha (mínimo de 10 caracteres): menu lateral, "Alterar senha".
- Criar outros usuários, trocar o e-mail ou redefinir senha (`python usuarios.py email NOME`): `python usuarios.py criar NOME`, `python usuarios.py senha NOME`, `python usuarios.py listar`, `python usuarios.py remover NOME`.

## Estrutura do Projeto

- `app.py`: Aplicação principal Flask.
- `serve.py`: Servidor de uso diário (waitress).
- `usuarios.py`: Gerência de usuários pelo terminal.
- `templates/`: Templates HTML.
- `static/`: Arquivos CSS e JS.
- `instance/uploads/`: Documentos anexados (cifrados).
- `seguranca.py`: criptografia, índices cegos e hash de senha.
- `config.py`: leitura dos segredos do `.env`.
- `supabase_schema.sql`: tabelas e travas (RLS) do banco.
- `gerar_chaves.py` / `migrar_sqlite.py`: criação do `.env` e migração do banco antigo.
- `tests/`: testes do módulo de segurança.

## Uso

- Navegue pelas abas para cadastrar tutores e animais.
- Use as abas de busca para encontrar e editar informações.
- Na aba de agendamentos, selecione um tutor para ver seus animais e agendar horários.
- Gere relatórios Excel conforme necessário.