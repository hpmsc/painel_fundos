#!/usr/bin/env Rscript
# coleta.R — execução orçamentária dos fundos da União via pacote orcamentoBR.
#
# O pacote orcamentoBR (MPO, CRAN) é a única porta de entrada: usamos apenas as
# funções públicas quaisMembros() e despesaDetalhada(). Nada de SPARQL escrito
# à mão — se o SIOP mudar, basta atualizar o pacote.
#
# Para cada exercício:
#   1. quaisMembros(ano, "UO") lista as unidades orçamentárias do ano;
#   2. selecionam-se as UOs de fundo: 3º dígito = 9 (padrão xx9xx dos fundos
#      especiais) OU descrição contendo "FUNDO";
#   3. despesaDetalhada() traz, por UO x Fonte x Resultado Primário x GND:
#      PLOA, LOA (dotação inicial), LOA + créditos (dotação atualizada),
#      empenhado, liquidado e pago;
#   4. grava dados/bruto/siop_AAAA.csv (só as UOs de fundo);
#   5. a partir de 2023 (codificação atual de fontes), grava também
#      dados/bruto/siop_fontes_AAAA.csv: execução, em QUALQUER UO, das fontes que o
#      MTO 2026 liga a fundos (dados/mto2026_fontes.csv). É o teste empírico do
#      vínculo fonte-fundo: mostra se a fonte roda na UO do fundo ou fora dela.
#
# Exercícios encerrados não mudam: só são coletados se o arquivo não existir.
# O exercício corrente e o anterior são sempre recoletados.
#
# Uso:
#   Rscript coleta.R                  # 2014..ano corrente, incremental
#   Rscript coleta.R 2024 2025        # só esses anos (força recoleta)
#
# Variáveis de ambiente opcionais:
#   ANO_INICIAL=2014
#   SIOP_IGNORAR_CERTIFICADO=1   repassa ignoreSecureCertificate=TRUE ao pacote
#                                (use só se a cadeia de certificados embutida no
#                                pacote expirar; desliga a verificação TLS).

invisible(Sys.setlocale("LC_CTYPE", "C.UTF-8"))

# (os testes injetam versões simuladas das funções antes de carregar o script)
if (!exists("despesaDetalhada")) suppressPackageStartupMessages(library(orcamentoBR))

DIR_BRUTO   <- "dados/bruto"
ANO_ATUAL   <- as.integer(format(Sys.Date(), "%Y"))
ANO_INICIAL <- as.integer(Sys.getenv("ANO_INICIAL", "2014"))
IGNORA_CERT <- identical(Sys.getenv("SIOP_IGNORAR_CERTIFICADO"), "1")
TENTATIVAS  <- 3
COLUNAS <- c("exercicio", "uo_cod", "uo_desc", "fonte_cod", "fonte_desc",
             "rp_cod", "rp_desc", "gnd_cod", "gnd_desc",
             "ploa", "loa", "loa_mais_credito", "empenhado", "liquidado", "pago")

dir.create(DIR_BRUTO, recursive = TRUE, showWarnings = FALSE)
msg <- function(...) cat(format(Sys.time(), "%H:%M:%S"), ..., "\n")

pad5 <- function(x) { x <- trimws(as.character(x)); n <- nchar(x)
  ifelse(n < 5, paste0(strrep("0", pmax(0, 5 - n)), x), x) }

sem_acento <- function(x) toupper(iconv(x, from = "UTF-8", to = "ASCII//TRANSLIT", sub = ""))

com_tentativas <- function(rotulo, expr_fn) {
  for (i in seq_len(TENTATIVAS)) {
    r <- tryCatch(expr_fn(), error = function(e) e)
    if (!inherits(r, "error")) return(r)
    msg("  falha", i, "/", TENTATIVAS, "em", rotulo, ":", conditionMessage(r))
    Sys.sleep(5 * i)
  }
  NULL
}

uos_de_fundo <- function(ano) {
  m <- com_tentativas(paste("quaisMembros", ano),
                      function() quaisMembros(ano, "UO", ignoreSecureCertificate = IGNORA_CERT))
  if (is.null(m) || nrow(m) == 0) return(NULL)
  names(m) <- c("uo_cod", "uo_desc")
  m$uo_cod <- pad5(m$uo_cod)
  fundo <- substr(m$uo_cod, 3, 3) == "9" | grepl("FUNDO", sem_acento(m$uo_desc), fixed = TRUE)
  m[fundo, , drop = FALSE]
}

padroniza <- function(df) {
  if (is.null(df) || nrow(df) == 0) return(NULL)
  mapa <- c(exercicio = "exercicio", UO_cod = "uo_cod", UO_desc = "uo_desc",
            Fonte_cod = "fonte_cod", Fonte_desc = "fonte_desc",
            ResultadoPrimario_cod = "rp_cod", ResultadoPrimario_desc = "rp_desc",
            GND_cod = "gnd_cod", GND_desc = "gnd_desc")
  for (n in names(mapa)) if (n %in% names(df)) names(df)[names(df) == n] <- mapa[[n]]
  for (c in COLUNAS) if (!c %in% names(df)) df[[c]] <- NA
  df <- df[, COLUNAS]
  for (c in c("ploa", "loa", "loa_mais_credito", "empenhado", "liquidado", "pago"))
    df[[c]] <- round(as.numeric(df[[c]]), 2)
  df
}

FONTES_FUNDO <- local({
  f <- "dados/mto2026_fontes.csv"
  if (file.exists(f)) unique(read.csv2(f, colClasses = "character", encoding = "UTF-8")$fonte_cod) else character()
})
ultimos3 <- function(x) { x <- trimws(as.character(x)); substr(x, pmax(1, nchar(x) - 2), nchar(x)) }

grava_csv <- function(df, arq) {
  tmp <- paste0(arq, ".tmp")
  for (c in names(df)) if (is.character(df[[c]])) df[[c]] <- enc2utf8(df[[c]])
  write.table(df, tmp, sep = ";", dec = ".", row.names = FALSE, na = "", quote = TRUE)
  file.rename(tmp, arq)
}

agrega_fontes <- function(df) {
  df <- df[ultimos3(df$fonte_cod) %in% FONTES_FUNDO, , drop = FALSE]
  if (nrow(df) == 0) return(NULL)
  chave <- paste(df$uo_cod, df$fonte_cod, sep = "|")
  soma <- function(col) tapply(df[[col]], chave, sum, na.rm = TRUE)
  prim <- !duplicated(chave)
  out <- df[prim, c("exercicio", "uo_cod", "uo_desc", "fonte_cod", "fonte_desc")]
  k <- chave[prim]
  for (col in c("loa", "loa_mais_credito", "empenhado", "pago")) out[[col]] <- as.numeric(soma(col)[k])
  out
}

coletar_fontes <- function(ano, tudo) {
  if (ano < 2023 || length(FONTES_FUNDO) == 0) return(invisible(NULL))
  cruz <- if (!is.null(tudo)) agrega_fontes(tudo) else NULL
  if (is.null(cruz)) {           # caminho seguro: uma consulta por fonte ligada a fundo
    m <- com_tentativas(paste("quaisMembros Fonte", ano),
                        function() quaisMembros(ano, "Fonte", ignoreSecureCertificate = IGNORA_CERT))
    if (is.null(m) || nrow(m) == 0) return(invisible(NULL))
    cods <- m[[1]][ultimos3(m[[1]]) %in% FONTES_FUNDO]
    partes <- list()
    for (fc in cods) {
      d <- com_tentativas(paste("Fonte", fc), function()
        despesaDetalhada(exercicio = ano, UO = TRUE, Fonte = fc, ignoreSecureCertificate = IGNORA_CERT))
      if (!is.null(d) && nrow(d) > 0) partes[[fc]] <- padroniza(d)
    }
    if (length(partes) == 0) return(invisible(NULL))
    cruz <- agrega_fontes(do.call(rbind, partes))
  }
  if (is.null(cruz)) return(invisible(NULL))
  cruz$uo_cod <- pad5(cruz$uo_cod); cruz$exercicio <- ano
  grava_csv(cruz, file.path(DIR_BRUTO, sprintf("siop_fontes_%d.csv", ano)))
  msg("  fontes ligadas a fundos:", nrow(cruz), "combinações UO x fonte")
}

detalhe <- function(ano, uo = TRUE) {
  despesaDetalhada(exercicio = ano, UO = uo, Fonte = TRUE, ResultadoPrimario = TRUE, GND = TRUE,
                   ignoreSecureCertificate = IGNORA_CERT)
}

coletar_ano <- function(ano) {
  msg("Exercício", ano)
  fundos <- uos_de_fundo(ano)
  if (is.null(fundos) || nrow(fundos) == 0) { msg("  sem UOs de fundo (ou SIOP indisponível)"); return(FALSE) }
  msg(" ", nrow(fundos), "UOs de fundo identificadas")

  # Caminho rápido: uma consulta com todas as UOs, filtrada aqui. Conferimos
  # contra o total do ano (consulta sem dimensões) para detectar truncamento.
  base <- NULL; completo <- NULL
  tudo <- com_tentativas(paste("despesaDetalhada", ano), function() detalhe(ano))
  total <- com_tentativas(paste("total", ano), function()
    despesaDetalhada(exercicio = ano, ignoreSecureCertificate = IGNORA_CERT))
  if (!is.null(tudo) && nrow(tudo) > 0 && !is.null(total) && nrow(total) > 0) {
    tudo <- padroniza(tudo)
    soma  <- sum(tudo$loa_mais_credito, na.rm = TRUE)
    ref   <- sum(as.numeric(total$loa_mais_credito), na.rm = TRUE)
    if (ref > 0 && abs(soma - ref) / ref < 0.001) {
      tudo$uo_cod <- pad5(tudo$uo_cod)
      completo <- tudo
      base <- tudo[tudo$uo_cod %in% fundos$uo_cod, , drop = FALSE]
      msg("  consulta única ok:", nrow(tudo), "linhas;", nrow(base), "de fundos")
    } else {
      msg("  consulta única incompleta (", format(soma, big.mark = ".", decimal.mark = ",", scientific = FALSE), "vs",
          format(ref, big.mark = ".", decimal.mark = ",", scientific = FALSE), ") — seguindo UO a UO")
    }
  }

  # Caminho seguro: uma consulta por UO de fundo.
  if (is.null(base)) {
    partes <- list()
    for (cod in fundos$uo_cod) {
      d <- com_tentativas(paste("UO", cod), function() detalhe(ano, uo = cod))
      if (!is.null(d) && nrow(d) > 0) partes[[cod]] <- padroniza(d)
    }
    if (length(partes) == 0) { msg("  nada coletado"); return(FALSE) }
    base <- do.call(rbind, partes)
    base$uo_cod <- pad5(base$uo_cod)
  }

  base$exercicio <- ano
  arq <- file.path(DIR_BRUTO, sprintf("siop_%d.csv", ano))
  grava_csv(base, arq)
  grava_csv(fundos, file.path(DIR_BRUTO, sprintf("uos_%d.csv", ano)))
  msg("  gravado", arq, "(", nrow(base), "linhas )")
  tryCatch(coletar_fontes(ano, completo), error = function(e) msg("  fontes: erro", conditionMessage(e)))
  TRUE
}

args <- commandArgs(trailingOnly = TRUE)
if (length(args) > 0) {
  anos <- as.integer(args); forcar <- anos
} else {
  anos <- ANO_INICIAL:ANO_ATUAL; forcar <- c(ANO_ATUAL - 1L, ANO_ATUAL)
}

falhas <- 0
for (ano in anos) {
  arq <- file.path(DIR_BRUTO, sprintf("siop_%d.csv", ano))
  if (file.exists(arq) && !(ano %in% forcar)) { msg("Exercício", ano, "já coletado — mantido"); next }
  ok <- tryCatch(coletar_ano(ano), error = function(e) { msg("  erro:", conditionMessage(e)); FALSE })
  if (!ok) falhas <- falhas + 1
}
msg("Fim. Exercícios com falha:", falhas)
quit(status = if (falhas > 0 && falhas == length(anos)) 1 else 0)
