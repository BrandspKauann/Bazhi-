# Bazhi Cluster — piloto Docker

Este pacote prepara a migração do verificador local para uma fila PostgreSQL com agentes distribuídos. **Não promete 300 consultas SMTP por segundo nem conclusão em 17 horas.** Esses números precisam ser comprovados com o provedor de hospedagem e os servidores de destino.

## O que muda

- Os agentes não disputam o arquivo SQLite do computador: somente a API acessa o PostgreSQL.
- Cada domínio tem uma reserva, com renovação, e os servidores MX têm um limite compartilhado.
- A conexão SMTP pode ser reaproveitada para até cinco endereços do mesmo domínio, mantendo o teste de catch-all.
- Não envia mensagens, não usa DATA, não pede senha de caixa de e-mail e não usa OpenAI.
- Mantém uma tentativa por endereço. Se um agente desaparecer depois de marcar o início, o resultado fica inconclusivo e não é repetido automaticamente.
- A fila começa pausada. Simulação e produção são bancos separados e não podem ser misturados.
- Logs Docker têm limite de tamanho; a migração é por blocos, sem gerar outros arquivos de milhões de endereços no disco local.

## Piloto no mesmo computador

É necessário Docker Desktop funcionando, Python 3 e espaço disponível para as imagens. **Docker não cria RAM, banda ou capacidade de processamento adicional no computador.** Este piloto consome recursos, portanto não inicie várias cópias para tentar compensar falta de hardware.

1. Extraia este pacote fora do ZIP.
2. Execute `INICIAR_PILOTO.cmd`. Isso cria chaves privadas em `.env` e sobe um projeto Docker separado chamado `bazhi-cluster-pilot`. Não altera o bot antigo, seus CMDs, arquivos, containers ou volumes.
3. Confira com `docker compose ps`.
4. Carregue somente dados fictícios:

```sh
docker compose exec -e COORDINATOR_URL=http://coordinator:8788 coordinator python admin.py seed-simulation --count 10000
docker compose exec -e COORDINATOR_URL=http://coordinator:8788 coordinator python admin.py enable
docker compose exec -e COORDINATOR_URL=http://coordinator:8788 coordinator python admin.py stats
```

O administrador usa a chave já presente no container; não é necessário exibi-la. No modo padrão `simulation`, o agente não faz DNS ou SMTP real. Resultados fictícios têm status `simulado` e nunca `smtp_aceito`.

Para encerrar **somente o piloto**, use `docker compose down` dentro desta pasta. **Não use `down -v`: isso removeria o volume de dados do piloto.** Não remova o SQLite antigo nem seu WAL.

## Testes automatizados e medição

Com um PostgreSQL de teste vazio disponível:

```sh
pip install -r requirements.txt
TEST_DATABASE_URL=postgresql://usuario:senha@localhost:5432/teste python -m unittest -v test_cluster.py
TEST_DATABASE_URL=postgresql://usuario:senha@localhost:5432/teste python benchmark.py
```

Cada teste cria um schema `test_...` aleatório e remove somente esse schema. O benchmark processa 5 mil tarefas fictícias com 32 clientes e grava `pilot-report.json`. **A taxa dessa medição é da fila e da gravação: não é taxa de validação SMTP.** Não extrapole o relatório para anunciar 300 e-mails reais por segundo.

Os testes cobrem reservas concorrentes, ausência de duplicação, autenticação por função, parada por padrão, retomada após perda de agente, importação idempotente, exportação fora de ordem e classificação de aceitação versus catch-all/política.

## Implantação em outro servidor

O mesmo Docker pode rodar em outra máquina. Para ganhar capacidade física, coloque os agentes em servidores com recursos próprios e saída SMTP na porta 25 autorizada pelo provedor. Antes de contratar, confirme essa permissão e a configuração de DNS reverso. Não há rotação de IP nem tentativa de contornar bloqueios.

1. Configure um domínio para a API do coordenador.
2. Preencha `COORDINATOR_DOMAIN` no `.env` e use o perfil TLS:

```sh
docker compose --profile remote up -d --build
```

Somente Caddy publica 80/443; a API direta fica em 127.0.0.1:8788 e o PostgreSQL não publica porta. Restrinja 80/443 e acesso administrativo no firewall. Caddy obtém HTTPS quando DNS e acessos estiverem corretos.

3. No servidor de cada agente, copie somente código e um arquivo privado `agent.env` com `COORDINATOR_URL=https://...`, `AGENT_TOKEN`, `NODE_NAME` único e `CONCURRENCY=16`. **Não copie o token administrativo ou a senha do PostgreSQL para os agentes.**

```sh
docker compose --env-file agent.env -f compose.agent.yml up -d --build
```

4. Para medir conectividade do servidor, execute `preflight.py --public-ip IP_DO_SERVIDOR --helo NOME_SMTP`. O teste consulta somente saudação SMTP, sem destinatário. PTR correto e porta 25 aberta não garantem aceitação de e-mails.

## Migrar o progresso sem refazer trabalho

### Piloto gratuito com agente nativo no Windows

Se o Docker não tem rota IPv6, mas o Windows consegue alcançar os MX por IPv6, a API e o PostgreSQL podem permanecer no Docker e o agente pode rodar nativamente. Isso evita mudar a rede do Windows ou encerrar os bots existentes; **não cria capacidade de hardware extra**.

`compose.native.yml` adiciona um coordenador local separado em 127.0.0.1:8789, conectado ao banco vazio `bazhi_live_pilot`. O banco precisa existir antes de subir esse serviço; não reutilize o banco de simulação. Nenhuma porta de PostgreSQL é exposta.

`sample_bridge.py` permite um teste pequeno e explicitamente autorizado. Reserva somente pendentes ainda sem tentativas e de domínios sem outro proprietário ativo, alterando seu estado para `cluster_pilot` para impedir a consulta simultânea pelo bot antigo. A reserva usa os índices existentes e tem um limite de execução de três segundos dentro da transação. Se não terminar, faz rollback; não force nem encerre os trabalhadores originais para obter a amostra.

O iniciador `start_native_pilot.py` exige exatamente 50 pendentes na fila nova e os argumentos `--start --confirm-50`, uma caixa real configurada e autorização do operador. Sem `--start`, faz somente uma conferência, sem SMTP. O token administrativo não é passado ao agente e nenhuma credencial é impressa ou colocada em argumentos de processo.

Quando os resultados terminarem, `sample_bridge.py --action reconcile --source-config CAMINHO/config.json` grava uma única tentativa por endereço na origem e só depois confirma o recebimento na API. A reconciliação é idempotente e não libera reservas de outros trabalhadores. Se a importação interromper antes de começar, `--action resume` reenvia a mesma reserva sem criar outra.

**Não apague a tabela `cluster_pilot_sample` nem restaure os pendentes manualmente durante o teste.** Uma amostra iniciada precisa ser reconciliada para não perder resultados nem repetir consultas. O teste de 50 endereços não comprova uma taxa de 300/s para os 18 milhões.

**Não é necessário parar o bot antigo para revisar ou testar este pacote. A parada coordenada só acontece no momento da migração real, depois de validar a infraestrutura.** Este programa não para nem apaga a origem.

1. Prepare um **banco novo vazio de produção**. Defina `CLUSTER_MODE=live` no coordenador. Não reaproveite o volume de simulação, não o apague por conveniência: escolha outro nome de projeto/volume.
2. Configure `SMTP_SENDER` com uma caixa real, `SMTP_HELO` com o nome correto e `ALLOW_REAL_SMTP=1` nos agentes. Deixe o processamento pausado.
3. Quando autorizado a mudar, use a parada do bot antigo e aguarde todas as reservas terminarem. Preserve `fila.sqlite`, `fila.sqlite-wal`, a base Receita e o banco atual. Não copie somente o SQLite principal enquanto há gravações.
4. Verifique a origem sem mudar nada:

```sh
python migrate.py --source-config "CAMINHO/config.json" --inspect
```

5. Configure no ambiente local `COORDINATOR_URL` HTTPS e o `ADMIN_TOKEN` privado. Só então execute:

```sh
python migrate.py --source-config "CAMINHO/config.json" --upload
```

O programa exige a origem pausada e sem reservas ativas. Importa resultados já existentes como concluídos, incluindo inconclusivos, e transfere pendentes sem repetir os analisados. Confirma cada lote no PostgreSQL e mantém um cursor remoto para retomar. Abre a origem somente para leitura e fecha a conexão entre os lotes. Endereços com NUL ou tamanho incompatível são preservados em base64 nos metadados e classificados sem nova consulta SMTP.

6. Compare as contagens e faça uma amostra dos resultados importados. Ative a nova fila somente depois dessa validação. A origem deve permanecer parada enquanto a nova fila trabalha.
7. Exporte resultados com `admin.py download --output resultados.jsonl`. O arquivo é confirmado em disco antes de enviar o ACK ao servidor. Uma interrupção entre gravação e ACK pode repetir linhas no arquivo; deduplique pelo campo `id`. Nenhum resultado é pulado por ter terminado fora de ordem.

**Este piloto ainda não altera automaticamente o workspace DuckDB nem a cópia Docker do site Bazhi.** A integração final dessas saídas deve ser validada durante a migração. Não apague a origem antes de conferir a importação, exportação e leitura pelos consumidores finais.

## Pausar e preservar

`admin.py pause` impede novas reservas. Os agentes terminam as tarefas já iniciadas. Volumes persistem ao recriar containers; perder um container não deve apagar os dados. Faça backups consistentes de PostgreSQL com `pg_dump`, teste restauração e mantenha cópia fora do servidor antes de apagar qualquer fonte antiga.

## Segurança e limites

`.env` contém credenciais privadas: não publique, não anexe a tarefas e não envie por chat. No Linux, restrinja sua permissão a 600; no Windows, restrinja a pasta ao seu usuário. Em produção, use backups, TLS e firewall. Não exponha PostgreSQL publicamente.

Mais servidores não eliminam catch-all, greylisting, políticas ou bloqueios por provedor. Meça resultados conclusivos, inconclusivos, timeouts, latência, uso de RAM e disco por pelo menos uma amostra representativa antes de ampliar o piloto.

Referências: [fila concorrente PostgreSQL](https://www.postgresql.org/docs/current/sql-select.html), [restrição de SMTP na EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-resource-limits.html), [SMTP](https://www.rfc-editor.org/rfc/rfc5321.html).
