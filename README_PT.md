# MvC2 Online (PS2 Japao) - sem modem

Substitui o modem/PPP do jogo por Ethernet (o PS2 Slim ja tem a porta). Versao 0.1: serve para
fazer o jogo "achar que esta online" e capturar o que ele envia ao servidor.

## 1. Descobrir o IP do seu PC
Windows: abra o Prompt de Comando e digite `ipconfig`. Anote o "Endereco IPv4" (ex.: 192.168.0.100).

## 2. Subir no GitHub e compilar (nada para instalar)
1. No GitHub: **New repository** (nome: `mvc2-online`, publico ou privado).
2. Extraia este zip no PC. No repositorio: **Add file > Upload files** e arraste TODO o conteudo
   (incluindo a pasta `.github`; se ela nao subir, use **Add file > Create new file**, digite
   `.github/workflows/build.yml` no nome e cole o conteudo do arquivo).
3. Abra `iop/avewrap/config.h` no GitHub (icone do lapis), troque `SERVER_IP_A..D` pelo IP do seu PC
   e clique em **Commit changes**.
4. Aba **Actions**: o build roda sozinho. Quando ficar verde (ou vermelho!), clique nele e baixe
   **mvc2-online** em "Artifacts". Se der ERRO, baixe mesmo assim e me mande `build_log.txt` e
   `sdk_info.txt` que estao dentro do zip (ou copie o texto vermelho do log).

## 3. Colocar na ISO (UltraISO)
1. Abra a ISO, entre na pasta `MODULES`.
2. Arraste TODOS os arquivos da pasta `MODULES` do artifact para dentro da `MODULES` da ISO,
   aceitando substituir os que ja existem (CXTMDM, OSTMDM_A, AVEPPP, AVE_WRAP, AVETCP, USB_SRCH) e adicionando
   os novos (PS2DEV9, NETMAN, SMAP, PS2IP, AVEWRAP2).
3. Salve a ISO (Arquivo > Salvar).

## 4. Testar
1. No PC: `python server/capture_server.py` (instale o Python se nao tiver). Libere o Python no
   firewall do Windows quando perguntar (redes privadas).
2. PS2 Slim: cabo de rede ligado ao roteador. Rode o jogo por USB/HDD (nao por SMB, que usa a
   mesma rede).
3. No jogo, va ao modo online e, se pedir tipo de modem, escolha qualquer um. Tente conectar.
4. Envie-me o arquivo `capture.log` que o servidor cria.

## O que ja esta decodificado
- RPC do jogo ao AVE_WRAP: ID 0x01270030, 22 comandos (ver comentario no topo de `avewrap.c`).
- PPP "conectado" = status 4. Mensagens Mcs: 1o byte = tamanho do registro (ou 0x28 = cabecalho de 12).
- Endereco original: host `ca1202.mmcp6` (substituido pelo IP do seu PC).

## Honestidade
Nada disso foi compilado nem testado em console ainda. Espere iterar: me mande os logs e eu ajusto.
O protocolo de login/lobby do servidor ainda precisa ser reconstruido a partir do que o jogo enviar.
