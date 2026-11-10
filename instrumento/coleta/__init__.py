"""A coleta confirmatória de ponta a ponta: a fila do plano, a pausa e o monitor.

  experimento.py coleta iniciar [--primeiro-plano]   confere tudo e roda a fila em segundo plano
  experimento.py coleta pausar                       cria PAUSAR: a execução atual termina e a coleta para
  experimento.py coleta retomar [--primeiro-plano]   apaga PAUSAR e continua de onde parou
  experimento.py coleta status                       um retrato do progresso
  experimento.py coleta monitor [--intervalo S]      o retrato, atualizado a cada S segundos (Ctrl+C sai; a coleta segue)

A fila é a da seção 8 do plano: um passo por parte do experimento, e cada passo grava um CSV só. Cada passo é um
`experimento.py rodar ...` (sem --ensaio); o rodar já pula o que tem linha no CSV, então parar e retomar nunca refaz
nem perde execução. Antes de cada passo, a coleta confere a
TRAVA-COLETA, o selo/MANIFEST.sha256 e a versão e o SHA-256 de cada cliente (fixados em fila.py): se algo
diferir, para sem rodar. As provas do selo (manifesto e carimbos OpenTimestamps) moram em selo/.

Módulos: fila (os dados do plano), diario (estado, pid e log), verificacao (o que
impede a coleta), progresso (o retrato) e processo (o laço e a linha de comando).
"""
