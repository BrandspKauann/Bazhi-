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

## Interface na Vercel e servidor local

Importe pela raiz do repositório. A Vercel publica o frontend e encaminha as rotas de API, inclusive o login, ao servidor persistente por `api/gateway.js`.

Configure como variáveis privadas de produção `BAZHI_BACKEND_URL` (endereço HTTPS da ponte) e `BAZHI_BRIDGE_SECRET` (chave compartilhada). Faça novo deploy após mudar as variáveis. A senha é validada no banco PostgreSQL do servidor; o acesso de demonstração não é usado pelas rotas normais.

`scripts/local-bridge.cjs` atende somente em `127.0.0.1:8787`, exige a chave em cada requisição e encaminha exclusivamente as rotas da aplicação para `127.0.0.1:8000`. Inicie com `node scripts/local-bridge.cjs caminho-do-config-privado.json`; o JSON deve conter `secret`, com pelo menos 32 caracteres aleatórios. O túnel HTTPS autorizado aponta para a porta 8787. Não exponha diretamente a porta 8000.

O computador, Docker, ponte e túnel precisam permanecer ligados. Se o endereço do túnel mudar, atualize `BAZHI_BACKEND_URL` e publique novamente. Os arquivos Receita são consultados em cópia local somente leitura nos volumes Docker; alterações nas segmentações da fonte exigem sincronizar essa cópia. Contatos, listas e tags importadas ficam no PostgreSQL persistente. Bases e chaves não são enviadas ao GitHub.

## Origem e licença

Bazhi é uma adaptação de [Quickly](https://github.com/AbdelftahZowail/Quickly), distribuído sob licença MIT. Os avisos originais foram preservados em [LICENSE](LICENSE). O README original está em [docs/UPSTREAM-README.md](docs/UPSTREAM-README.md). As fontes Inter e Montserrat incluem suas respectivas licenças em `frontend/src/assets/fonts/`.
