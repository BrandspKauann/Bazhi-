# Prospecção na base Receita

A página `/receita` combina os cadastros ativos de outubro/2026 com as tags, os segmentos dinâmicos e as checagens já salvas na base local. As três fontes são montadas somente para leitura pelo `compose.local.yml`:

- `/receita/EmpresasAtivas.parquet`: empresas ativas, uma por raiz de CNPJ.
- `/receita-tags/sql/workspace.duckdb`: tags B2B, classificação de e-mails e resultados SMTP/RH.
- `/receita-tags/operacoes.duckdb`: segmentos salvos e revisões de classificação.
- `/receita-leads/base-de-trabalho.json`: aponta para o Parquet de contatos classificados, no mesmo diretório montado.

Os caminhos podem ser ajustados com `RECEITA_PARQUET`, `RECEITA_WORKSPACE`, `RECEITA_OPERACOES` e `RECEITA_LEADS_DIR`. A competência exibida nesta versão é outubro/2026.

## Filtros

O catálogo de sugestões é lido dos valores reais das tags e dos segmentos ativos. A interface busca por partes do nome, termos relacionados e pequenas diferenças de digitação. Vários segmentos usam a regra **qualquer um** (OU); localização, canais e confiabilidade combinam-se com **todos os filtros** (E).

O filtro de telefone considera os dois números cadastrais. É presença de número com ao menos oito dígitos, sem confirmação de funcionamento ou WhatsApp. O filtro de e-mail corporativo utiliza a classificação salva e o mesmo domínio atual, sem presumir titularidade.

Confiabilidade usa sempre a raiz de CNPJ **e o endereço de e-mail atual**. Um resultado SMTP/RH tem prioridade sobre o teste legado para o mesmo endereço:

- **SMTP comprovado:** aceitação RCPT 250/251 registrada no teste legado; ou SMTP_ACEITO com catch-all não detectado no teste RH.
- **Inconclusivo:** existe uma checagem sem conclusão. Catch-all e falhas temporárias/conexão ficam nesta categoria.
- **Não verificado:** sem evidência para o endereço atual ou verificação pendente.
- **Recusado / inválido:** recusa RCPT definitiva registrada ou erro de formato/DNS classificado como inválido.

Aceitação SMTP significa aceitação na checagem salva, não comprovação de entrega, titularidade ou validade atual. A busca não executa SMTP nem inicia novas verificações.

## Listas e contatos

Cada usuário pode salvar seleções de até 50 empresas. A lista guarda uma cópia dos resultados e os filtros utilizados; reabrir a lista mostra essa cópia. Ao adicionar aos contatos, o sistema consulta os registros e tags atuais novamente.

A importação copia as tags e metadados para `custom_data`, sem converter evidência antiga em nova verificação no Quickly. E-mails existentes recebem as tags e referências das listas, preservando os dados anteriores e o cancelamento de inscrição. Empresas sem e-mail de formato válido permanecem na lista e são ignoradas na importação para contatos de e-mail.

Rotas autenticadas:

- `GET /api/receita/segmentos`
- `GET /api/receita/empresas` (parâmetro repetido `segmentos`, `uf`, `com_email`, `telefone`, `tipo_email`, `confiabilidade`)
- `GET/POST /api/receita/listas`
- `GET /api/receita/listas/{id}` (somente proprietário)
- `POST /api/receita/importar` com `cnpjs` e `lista_id` opcional

Limites: até 50 empresas por consulta/lista; refine os filtros quando houver mais resultados. Esta versão não associa contatos diretamente a campanhas.

## Validação

`tests/test_receita_prospecting.py` usa dados sintéticos para testar as combinações de segmentos, revisões salvas, telefone secundário, evidência do mesmo endereço, prioridade das checagens, rejeição de segmentos inválidos e limite de 50.
