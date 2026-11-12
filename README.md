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

## Servidor e interface na Vercel

Importe pela raiz do repositório. O `vercel.json` publica a interface e a API Python nativa (`api/index.py`). Não é necessário túnel ou servidor no computador para criar contas online.

Conecte um banco PostgreSQL pelo Storage da Vercel (por exemplo, Neon). A integração precisa definir `DATABASE_URL` ou `POSTGRES_URL`. Faça um novo deploy após conectar o banco. Ao abrir o site, crie uma nova conta de administrador com usuário, e-mail e senha. As contas e os dados do computador não são copiados automaticamente.

O modo Vercel desativa o agendador permanente por instância. Cadastro, login e rotas de gestão são atendidos por requisição; envios programados e sincronizações periódicas precisam de um worker ou cron apropriado antes de serem usados em produção. A base local da Receita continua fora do GitHub e não estará disponível na nuvem sem uma migração separada.

As dependências da função estão em `api/requirements.txt`, sem instalar todos os SDKs opcionais de IA. As variáveis históricas `QUICKLY_*` são mantidas por compatibilidade. É possível definir uma chave `QUICKLY_SECRET_KEY` própria; na ausência dela a API na Vercel deriva uma chave estável da credencial privada do banco.

## Origem e licença

Bazhi é uma adaptação de [Quickly](https://github.com/AbdelftahZowail/Quickly), distribuído sob licença MIT. Os avisos originais foram preservados em [LICENSE](LICENSE). O README original está em [docs/UPSTREAM-README.md](docs/UPSTREAM-README.md). As fontes Inter e Montserrat incluem suas respectivas licenças em `frontend/src/assets/fonts/`.
