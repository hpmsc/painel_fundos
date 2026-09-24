# Painel dos Fundos Públicos da União

Painel estático (GitHub Pages) para controle dos fundos da União. Ele mostra:

- **dotação, empenho e pagamento** de cada fundo, de 2014 até hoje, com PLOA, LOA, dotação atualizada, empenhado, liquidado e pago;
- a **identificação composta** de cada fundo (UO + fonte + UG/Gestão + CNPJ), porque não há um código exclusivo de fundo entre os classificadores do orçamento;
- o **histórico de classificações** tirado do ET nº 01/2026 (Conof/CD): dicotomia do Decreto 93.872/1986, categoria mista de Bassi (2019), listas do Acórdão TCU 1.494/2021, normas e fiscalizações posteriores;
- a **verificação com o MTO 2026**: fontes, UOs e naturezas de receita que se conectam a fundos, cruzadas com a execução observada.

Segue o modelo do [painel_TCU](https://github.com/atrfisch/painel_TCU): um coletor roda no GitHub Actions, grava os dados no repositório e publica `site/` no Pages.

## Estrutura

```
coleta.R                  coleta no SIOP pelo pacote R orcamentoBR (MPO/CRAN)
montar.py                 junta cadastro, classificações, MTO e execução em site/dados.json
mto.py                    extrai do texto do MTO 2026 os códigos ligados a fundos (roda uma vez)
dados/
  fundos.csv              CADASTRO: um fundo por linha (edite aqui UG, CNPJ, padrões de nome)
  classificacoes.csv      histórico de classificações por fundo (ET 01/2026)
  marcos.csv              linha do tempo de normas, tipologias e decisões (ET 01/2026)
  mto2026_uos.csv         classificação institucional do MTO 2026 (478 UOs, 60 de fundo)
  mto2026_fontes.csv      66 fontes do MTO 2026 ligadas a fundos, com o tipo de vínculo
  mto2026_receitas.csv    naturezas de receita que citam fundo
  semente_bassi_2018.csv  execução 2018 (Bassi, TD Ipea 2458, Tab. 3), usada até a 1ª coleta
  bruto/                  gerado pela coleta: siop_AAAA.csv, siop_fontes_AAAA.csv, uos_AAAA.csv
site/
  index.html              o painel
  dados.json              gerado por montar.py
tests/teste_coleta.R      teste offline do coleta.R com o orcamentoBR simulado
.github/workflows/atualizar-painel.yml
```

## Publicar

1. Crie um repositório no GitHub e envie estes arquivos para a branch `main`.
2. Em **Settings > Pages**, escolha **Source = GitHub Actions**.
3. Em **Settings > Actions > General**, marque **Read and write permissions**.
4. Em **Actions > Atualizar painel de fundos**, clique em **Run workflow**. A primeira execução coleta de 2014 até o ano corrente. As seguintes, em dias úteis às 7h de Brasília, recoletam só o exercício corrente e o anterior.

O endereço do painel aparece no fim do job `publicar` (algo como `https://SEU-USUARIO.github.io/NOME-DO-REPO/`).

## Como a coleta funciona

`coleta.R` usa apenas as funções públicas do **orcamentoBR**:

- `quaisMembros(ano, "UO")` lista as UOs do ano. Entram como fundo as UOs com 3º dígito 9 (padrão xx9xx) ou com "Fundo" no nome, o que inclui as UOs 749xx ("Recursos sob Supervisão do Fundo…").
- `despesaDetalhada(ano, UO = TRUE, Fonte = TRUE, ResultadoPrimario = TRUE, GND = TRUE)` traz PLOA, LOA, LOA + créditos, empenhado, liquidado e pago. A soma é conferida contra o total do ano; se a consulta única vier truncada, o script refaz UO a UO.
- De 2023 em diante (codificação atual de fontes), também grava onde, em qualquer UO, são executadas as fontes que o MTO 2026 liga a fundos. É o teste empírico do vínculo fonte-fundo.

Se a cadeia de certificados que o orcamentoBR embute expirar, rode com `SIOP_IGNORAR_CERTIFICADO=1` (desliga a verificação TLS; use só como paliativo e atualize o pacote).

Rodar localmente:

```bash
Rscript -e 'install.packages("orcamentoBR")'
Rscript coleta.R            # incremental, 2014..ano corrente
Rscript coleta.R 2025 2026  # só esses anos
python3 montar.py
cd site && python3 -m http.server 8000   # abra http://localhost:8000
```

## Identificação de cada fundo

O `id` do cadastro é a chave do painel. A cada exercício, `montar.py` associa as UOs do SIOP ao fundo pelo **padrão de nome** (`padrao_uo`, regex sobre o nome sem acentos), depois pela **sigla** citada no nome ("Supervisão do FNO") e por fim pelo **código de UO de referência**. Assim o painel acompanha trocas de código, por exemplo FNCA 30913 (2018) → 81901 (2026) ou Funset 56901 → 39905. UO de fundo que não case com o cadastro aparece como `UO-xxxxx` ("sem cadastro"), para ninguém sumir da lista.

UG/Gestão e CNPJ não estão no SIOP: preencha as colunas `ug` e `cnpj` de `dados/fundos.csv` (várias UGs ou fontes separadas por `|`). Texto com `;` precisa estar entre aspas; `montar.py` recusa linhas com colunas a mais.

## Limites

- "Volume financeiro" no painel é o montante orçamentário (dotação, empenho, pagamento). Saldos, superávit financeiro e patrimônio de cada fundo não estão no SIOP e exigem outra fonte (Balanço Geral da União, Tesouro Gerencial ou relatórios dos gestores).
- Os vínculos fonte-fundo marcados **"a verificar"** são hipóteses por afinidade temática. O painel mostra quanto da dotação de cada fonte está nas UOs do fundo ligado; confirme antes de citar.
- Fundos de natureza privada (FIPEM, FNDIT) e fundos sem UO própria aparecem no cadastro e no histórico. A execução deles, quando existe, só aparece pela fonte vinculada.
- A semente de 2018 soma R$ 314,96 bi de dotação atualizada nas 39 linhas impressas da Tabela 3 de Bassi, contra R$ 317,44 bi no total da tabela. A diferença (R$ 2,48 bi) corresponde a linhas que não aparecem impressas (FNC, FNMA e FNMC na dimensão contábil, citados no texto).

## Fontes

- SIOP — endpoint de dados abertos, via [orcamentoBR](https://cran.r-project.org/package=orcamentoBR) (MPO).
- Rego, Oliveira e Volpe. *Classificação e Controle de Fundos na União*. Estudo Técnico nº 01/2026, Conof/Câmara dos Deputados, mar. 2026.
- Bassi, C. M. *Fundos especiais e políticas públicas*. Texto para Discussão 2458, Ipea, 2019.
- SOF/MPO. *Manual Técnico de Orçamento — MTO 2026*.
