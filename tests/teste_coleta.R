# Teste offline de coleta.R: substitui as funções do orcamentoBR por versões
# simuladas com o mesmo formato de saída (nomes de colunas do pacote 1.0.5).
# Uso: Rscript tests/teste_coleta.R   (grava em dados/bruto de um diretório temporário)
set.seed(1)
UOS <- data.frame(
  cod = c("36901","40901","24901","74913","30913","81901","26298","36211","52921","93000"),
  desc = c("Fundo Nacional de Saúde","Fundo de Amparo ao Trabalhador",
           "Fundo Nacional de Desenvolvimento Científico e Tecnológico",
           "Recursos sob Supervisão do Fundo Constitucional de Financiamento do Norte/FNO",
           "Fundo Nacional para a Criança e o Adolescente","Fundo Nacional para a Criança e o Adolescente",
           "Fundo Nacional de Desenvolvimento da Educação","Fundação Nacional de Saúde",
           "Fundo do Exército","Reserva de Contingência"))
uos_do_ano <- function(ano) {
  u <- UOS
  if (ano >= 2023) u <- u[u$cod != "30913", ] else u <- u[u$cod != "81901", ]
  u
}
linhas <- function(ano, cods) {
  out <- list()
  for (cod in cods) { set.seed(ano * 100000 + as.integer(cod)); for (f in c("1000","1050","1044","1068")) for (rp in c("1","2")) for (g in c("3","4","5")) {
    base <- as.numeric(substr(cod,1,2)) * 1e8 * (1 + (ano - 2020) * 0.05)
    loa <- round(base * runif(1, .2, 1), 2)
    out[[length(out)+1]] <- data.frame(exercicio = as.character(ano), UO_cod = cod,
      UO_desc = UOS$desc[UOS$cod == cod], Fonte_cod = f, Fonte_desc = paste("Fonte", f),
      ResultadoPrimario_cod = rp, ResultadoPrimario_desc = ifelse(rp=="1","Primário obrigatório","Primário discricionário"),
      GND_cod = g, GND_desc = c("3"="Outras Despesas Correntes","4"="Investimentos","5"="Inversões Financeiras")[[g]],
      ploa = as.character(loa*0.98), loa = as.character(loa), loa_mais_credito = as.character(loa*1.05),
      empenhado = as.character(loa*0.8), liquidado = as.character(loa*0.7), pago = as.character(loa*0.65))
  } }
  do.call(rbind, out)
}
quaisMembros <- function(exercicio, dimensao, ignoreSecureCertificate = FALSE) {
  if (dimensao == "Fonte") return(data.frame(Fonte_cod = c("1000","1050","1044","1068"), Fonte_desc = "x"))
  u <- uos_do_ano(exercicio); data.frame(UO_cod = u$cod, UO_desc = u$desc)
}
despesaDetalhada <- function(exercicio, UO = FALSE, Fonte = FALSE, ResultadoPrimario = FALSE, GND = FALSE,
                             ignoreSecureCertificate = FALSE, ...) {
  todos <- linhas(exercicio, uos_do_ano(exercicio)$cod)
  if (isFALSE(UO) && isFALSE(Fonte)) {
    s <- sum(as.numeric(todos$loa_mais_credito))
    if (exercicio == 2024) s <- s * 2   # simula truncamento em 2024 -> força caminho UO a UO
    return(data.frame(exercicio = as.character(exercicio), loa_mais_credito = as.character(s)))
  }
  if (is.character(UO)) return(todos[todos$UO_cod == UO, ])
  if (is.character(Fonte)) return(todos[todos$Fonte_cod == Fonte, ])
  todos
}
Sys.setenv(ANO_INICIAL = "2021")
source("coleta.R")
