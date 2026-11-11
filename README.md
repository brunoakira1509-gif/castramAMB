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
2. Crie o `.env` com as chaves: `python gerar_chaves.py`. Preencha `SUPABASE_URL` e `SUPABASE_PUBLISHABLE_KEY` com os dados do projeto (Project Settings > API Keys).
3. No Supabase: **SQL Editor > New query**, cole o conteúdo de `supabase_schema.sql` e clique em **Run**
   (cria/atualiza as tabelas e trava o acesso pelas chaves públicas). Se já executou uma versão anterior, rode novamente
   para acrescentar a coluna de espécie sem apagar os dados. Confira que todas as linhas mostram `rls_ativo = true`.
4. No Supabase: botão **Connect** > **Direct** > método **Transaction pooler** > formato **URI**. Troque `[YOUR-PASSWORD]`
   pela senha do banco e cole em `DATABASE_URL` no `.env`.
5. Tinha dados no sistema antigo (SQLite)? Rode `python migrar_sqlite.py`. Depois de conferir, apague
   `instance/castramovel.db` e `instance/uploads` antigos (estão em texto claro).
6. Crie e confirme as contas em **Supabase > Authentication > Users**. Inicie (`iniciar_servidor.bat` ou `python serve.py`)
   e acesse http://localhost:5000/ para entrar. O app cria o perfil local após o primeiro login confirmado.
   Se apenas administradores devem criar contas, desative o cadastro público nas configurações de Auth.

Configure o envio de e-mail no Supabase Auth se quiser que links de confirmação sejam enviados para usuários fora da equipe do projeto.
No Vercel, configure também `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `DATABASE_URL` e as quatro chaves `CASTRAMOVEL_*` no ambiente Production. Não são necessárias variáveis `SMTP_*` no Vercel.

## Segurança

- **Segredos fora do código**: tudo no `.env` (ignorado pelo git). O navegador nunca recebe chave, senha do banco ou URL do banco.
- **Dados criptografados** (AES-256-GCM) antes de ir ao banco: nome, telefone, CPF, endereço, número do tutor; nome, raça, sexo e microchip do animal; nome dos documentos. Os arquivos anexados também são cifrados no disco.
  Ficam em claro apenas ids, data/hora dos agendamentos e o nome de login.
- **Relatórios Excel**: o servidor descriptografa em memória só para montar a planilha; nada em claro vai para o disco.
- **Autenticação**: Supabase Auth valida e-mail e senha; usuários precisam confirmar o e-mail antes de entrar, conforme a configuração do projeto. O app só apresenta a tela de login; os usuários são gerenciados no Supabase.
- **Senhas**: gerenciadas pelo Supabase Auth. Usuários existentes migram no primeiro login válido; a senha atual é validada pelo hash legado e registrada no Auth.
- **Injection**: todas as consultas são parametrizadas (SQLAlchemy), entradas são validadas, o HTML é escapado e as planilhas
  neutralizam fórmulas (`=`, `+`, `-`, `@`).
- **Navegador**: proteção CSRF, cookie HttpOnly, política CSP (bloqueia script/estilo injetado), cabeçalhos de segurança, sem cache.
- **Supabase**: RLS ligado e sem policies nas tabelas do app. A chave publishable/anon só é usada pelo servidor para o endpoint de autenticação; os dados são acessados pelo app via PostgreSQL.
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

- Entrar usando o e-mail e a senha cadastrados; a senha precisa ter no mínimo 10 caracteres.
- Alterar a própria senha: menu lateral, "Alterar senha". Sem SMTP, não há recuperação por e-mail.
- Criar usuários: `python usuarios.py criar NOME`. Trocar o e-mail: `python usuarios.py email NOME`. Alterar a senha pelo terminal exige a senha atual: `python usuarios.py senha NOME`.
- Listar ou remover usuários: `python usuarios.py listar` e `python usuarios.py remover NOME`.

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