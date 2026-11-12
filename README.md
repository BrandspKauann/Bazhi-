# Bazhi

Software de prospecção com campanhas de e-mail, gestão de contatos e segmentação de empresas da Receita Federal.

## Recursos desta versão

- Interface em português, identidade visual Bazhi e temas claro/escuro.
- Busca por segmentos e tags salvos, filtros de canais de contato e evidências SMTP existentes.
- Listas de até 50 empresas e importação com tags personalizadas.
- Filtro por tag em Contatos, incluindo exportação e seleção em lote.
- Campanhas, sequências, caixa de entrada e relatórios da plataforma original.

## Executar o sistema completo

O servidor usa Python/FastAPI, PostgreSQL e um agendador contínuo. O Dockerfile constrói também a interface React/Vite.

1. Copie `.env.example` para `.env` e configure uma chave `QUICKLY_SECRET_KEY` estável e aleatória.
2. Configure PostgreSQL e `DATABASE_URL`, `BASE_URL` e `CORS_ORIGINS` para o ambiente.
3. Construa e execute o Dockerfile em um servidor contínuo com HTTPS e armazenamento persistente.
4. Configure Google/Microsoft OAuth ou SMTP para enviar e-mails.

As variáveis históricas `QUICKLY_*` foram preservadas para compatibilidade. Consulte [a instalação original](docs/INSTALL.md) e [a integração Receita](docs/RECEITA.md).

## Interface na Vercel

Importe este repositório na Vercel usando a **raiz do repositório**. O `vercel.json` instala e constrói `frontend/`, entrega a aplicação e encaminha as chamadas ao servidor.

Configure **`BAZHI_BACKEND_URL`** na Vercel com o endereço HTTPS de um servidor Bazhi já em funcionamento e faça um novo deploy. No servidor, `BASE_URL` deve ser o endereço público usado para acessar o Bazhi na Vercel. Ajuste também `CORS_ORIGINS` e os retornos OAuth.

**Conectar somente o GitHub à Vercel não coloca o sistema completo em operação.** A base Receita atualmente é local; seus arquivos não estão neste repositório e a Vercel não acessa o disco do computador. O servidor que executa o agendamento precisa ter acesso autorizado a esses arquivos e aos bancos de segmentações. Sem `BAZHI_BACKEND_URL`, a interface exibe uma mensagem de servidor não configurado.

O proxy de autenticação e API incluído deve ser validado com o endereço e os provedores OAuth do ambiente de produção antes de uso real. O banco, as contas, os segredos e os dados cadastrais não são publicados no GitHub.

## Origem e licença

Bazhi é uma adaptação de [Quickly](https://github.com/AbdelftahZowail/Quickly), distribuído sob licença MIT. Os avisos originais foram preservados em [LICENSE](LICENSE). O README original está em [docs/UPSTREAM-README.md](docs/UPSTREAM-README.md). As fontes Inter e Montserrat incluem suas respectivas licenças em `frontend/src/assets/fonts/`.
