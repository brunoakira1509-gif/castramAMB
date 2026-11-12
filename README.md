# CastraMóvel - Sistema de Organização

Este é um sistema web para organizar o serviço móvel de castração de animais (Cães e Gatos).

## Funcionalidades

- Cadastro de Tutores (donos dos animais) com informações pessoais e anexos de documentos.
- Cadastro de Animais vinculados aos tutores.
- Busca por Tutores e Animais.
- Agendamento de castrações (segunda a sexta-feira) em **horários fixos, com vagas por categoria** (veja abaixo).
- **Início** mostra só a agenda de hoje; a aba **Calendário** mostra o mês inteiro, dias futuros e registros anteriores.
- Perfis de tutor e de animal (com histórico de agendamentos) acessíveis por clique em qualquer agenda.
- Anexos dos tutores com visualização dentro do sistema (PDF e imagens).
- Geração de relatórios em Excel para agendas mensais ou diárias.

## Horários e vagas

| Horário | Quem pode | Vagas |
|---|---|---|
| 08:00 | gatas (felinos fêmeas) | 2 |
| 08:30 | cães ou gatos **machos** (as 3 vagas são compartilhadas) | 3 |
| 09:30 | cadela (cão fêmea) | 1 |
| 13:00 | cadela (cão fêmea) | 1 |
| 14:30 | 1 cão macho **e** 1 cadela | 1 + 1 |

Nenhum outro horário pode ser agendado. As regras são conferidas no servidor (não só na tela). Para mudar horários
ou quantidades, edite apenas a lista `GRADE` em `agenda_regras.py`. Cada animal só pode ter um agendamento a partir de
hoje (cancele para reagendar). Não é possível mudar espécie/sexo de um animal com agendamento futuro.

## Tecnologias

- Backend: Flask (Python)
- Banco de Dados: PostgreSQL no Supabase (dados pessoais criptografados pelo app)
- Frontend: HTML, CSS, JavaScript básico

## Instalação

1. Instale as dependências: `pip install -r requirements.txt`
2. Crie o `.env` com as chaves: `python gerar_chaves.py`. Preencha `SUPABASE_URL` e `SUPABASE_PUBLISHABLE_KEY` com os dados do projeto (Project Settings > API Keys).
3. No Supabase: **SQL Editor > New query**, cole o conteúdo de `supabase_schema.sql` e clique em **Run**
   (cria/atualiza as tabelas e trava o acesso pelas chaves públicas). Se já executou uma versão anterior, rode novamente
   para aplicar as mudanças sem apagar os dados. **Obrigatório ao atualizar para esta versão:** o script remove a trava
   antiga de "1 animal por data/hora" (sem isso o banco recusa a segunda vaga do mesmo horário) e acrescenta a coluna
   `conteudo` dos documentos. Confira que todas as linhas mostram `rls_ativo = true`.
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
- **Dados criptografados** (AES-256-GCM) antes de ir ao banco: nome, telefone, CPF, endereço, número do tutor; nome, raça, sexo e microchip do animal; nome dos documentos. Os arquivos anexados também são cifrados, e agora ficam no banco (coluna `conteudo`), não mais no disco.
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

- Um PC é o servidor: só ele guarda o `.env`; o banco (inclusive os anexos cifrados) fica no Supabase. Anexos antigos em `instance/uploads/` continuam abrindo.
- No servidor, execute `liberar_firewall.bat` como administrador (uma vez). Ele libera a porta 5000 apenas para redes privadas.
- Ao iniciar, `serve.py` mostra o endereço da rede, por exemplo `http://192.168.0.15:5000`. Abra esse endereço nos outros PCs.
- Reserve o IP do servidor no roteador para o endereço não mudar.
- Não faça redirecionamento de portas no roteador: o sistema deve ficar só na rede local.
- Faça backup do `.env` com frequência (e de `instance/uploads/`, se ainda tiver anexos antigos).

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
- `agenda_regras.py`: horários, categorias, vagas e funções do calendário (sem dependência de banco).
- `instance/uploads/`: só anexos antigos (os novos ficam no banco).
- `seguranca.py`: criptografia, índices cegos e hash de senha.
- `config.py`: leitura dos segredos do `.env`.
- `supabase_schema.sql`: tabelas e travas (RLS) do banco.
- `gerar_chaves.py` / `migrar_sqlite.py`: criação do `.env` e migração do banco antigo.
- `tests/`: testes de segurança, das regras de agenda (`python -m unittest discover tests`) e das telas.

## Uso

- Navegue pelas abas para cadastrar tutores e animais.
- Use as abas de busca para encontrar e editar informações.
- Em **Novo agendamento**: busque o tutor (nome ou CPF), escolha o animal, a data e um dos horários disponíveis.
  Horários que não atendem o animal ou estão lotados aparecem esmaecidos, com o motivo.
- No **Calendário**, clique num dia para ver horários, animais, espécie e tutores; clique no nome do animal ou do tutor
  para abrir o perfil. Agendamentos de hoje em diante podem ser cancelados; dias anteriores ficam como registro.
- Em um tutor, clique em um anexo para visualizá-lo ("Abrir em nova aba" e "Baixar" também estão na página).
- Gere relatórios Excel conforme necessário.