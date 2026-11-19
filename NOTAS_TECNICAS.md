# Notas tecnicas - Capcom vs. SNK 2 Millionaire Fighting 2001 (SLPM-65047)

ELF MIPS little-endian, base 0x100000, sem simbolos. Enderecos abaixo sao virtuais do EE.

## Igual ao MvC2
- RPC IOP: USB_SRCH 0x01270010, AVE_WRAP 0x01270030. Buffer RPC: +24 resultado, argumentos a partir de +28.
- Host `ca1201.mmcp6`, PPP "186,005363121201" / mmducp1 / cpcm1 (strings em 0x3e36a0..0x3e3700); "1000" em 0x3e3730.
- Maquina de conexao em 0x314a00: DnsGetTicket -> DnsLookup -> TcpOpen. Porta 0x9426 (=9876, ordem de rede) ou 0xe425 (=9700) quando modo 0.
- Laco de recepcao 0x335d70: TcpStat (+36 = bytes disponiveis) ; com >=12 le cabecalho de 12 bytes, tamanho be16 em [4..5].
- Vocabulario de mensagens identico ao MvC2: 0x6001-0x6004, 0x6101-0x6124, 0x6131-0x613A, 0x6141-0x6149, 0x62xx, 0x63xx, 0x64xx, 0x65xx, 0x67xx, 0x68xx, 0x69xx (imediatos no ELF, emissores perto de 0x323000-0x326a00, maquinas de estado 0x315000-0x31d000).
- Tabela de modems USB em 0x3a27a0: 05db:{7,6,5,3,2,1}, 0590:{e,b,1a,1d}, 0572:{1272,1232}. 0572:1272 -> CXTMDM.

## DIFERENTE do MvC2
- AVE_WRAP.IRX do CvS2 = "Tcp wrapper 2001.07.12". Enum FNO do proprio IRX: 0 Getconfig 1 Ifconfig 2 Ifdown 3 SetOpt 4 GetOpt 5 TcpInit 6 TcpTerm 7 TcpOpen 8 POpen 9/10 Accept 11 TcpClose 12 Abort 13 Getaddr 14 TcpStat 15 TcpSend 16/17 SendNb 18 TcpRecv 19 RecvNb 20 Cancel ... 31 PppInit 32 PppDisp 33 PppStart 34 PppFinish 35 PppStatus 36 PppUsbDeviceId 37/38 PppOption 39-42 Nd 43-55 Dhcp 56 DnsInit 57 DnsDisp 58 DnsGetTicket 59 DnsReleaseTicket 60 DnsLookup 61 DnsLookupRev 62 DnsGetTicketInfo 63-77 Com*.
  (No MvC2 o DNS era 57-61 e havia Mcs 64/65/67; aqui NAO ha Mcs.)
- Comandos que o EE realmente usa (stubs 0x3400a0..0x340f30): 5,6,7,11,14,15,18,31,32,33,34,35,56,57,58,60 (+59 provavel).
- DnsLookup: o jogo so aceita res=1 (IP em +32). res=0 vira erro.
- PppStatus: fase em res (+24) E em +36 (u16); +46 = last_error (0 = ok). Fase 4 = conectado; o jogo usa a fase como codigo 0..7 (tabela 0x3e4430).
- Modulo extra ACC_COM.IRX (RPC 0x01270020, API serial Com*, cmds 1..8, layout compacto sem cabecalho: retorno na 1a palavra). Cliente RPC em 0x54eaa0. O stub responde 0 a tudo (formato ainda nao confirmado).
- Driver extra OMMODEM.IRX (tipos 3 e 4 da tabela). Sequencia de carga: USB_SRCH -> driver -> AVEPPP -> ACC_COM -> AVE_WRAP (0x2e0040-0x2e0540).

## Substituicao (projeto)
CXTMDM/OMMODEM/OSTMDM_A -> loader (carrega PS2DEV9, NETMAN, SMAP, PS2IP, AVEWRAP2) | AVEPPP/AVETCP/AVE_WRAP -> vazio |
ACC_COM -> stub | USB_SRCH -> substituto (0572:1272) | AVEWRAP2 -> AVE_WRAP sobre lwIP (DHCP + descoberta UDP 9999).

## Servidor
server/capture_server.py = servidor v23 do MvC2 renomeado (CVS2-DISCOVER/CVS2-SERVER), portas 9876/9700/1000.
Serve de ponto de partida; o que o CvS2 mandar de diferente aparece como NOVO no capture.log.

## Proximos passos
1. Compilar, trocar modulos na ISO, rodar e enviar capture.log.
2. Ver se o jogo chega a TcpOpen e as primeiras mensagens (0x6001/0x6004/0x6101...).
3. Ajustar o stub ACC_COM se o jogo travar no bind/carga.

## Modem virtual / luta (v0.4) - decifrado no ELF
Apos o 6906 o jogo manda 6002 (logout), derruba a pilha AVE (cmds 57/32/6) e entra em `network_mode04` (0x15c3b4):
fase 0 `modem_module_initialize` (carrega AVETCP/USB_SRCH, bind RPC, busca modem USB) -> fase 1 `modem_connect` -> fase 2 `match_IO_sync` -> luta.
- API Com* (RPC 0x01270020, cliente em 0x54eaa0, buffer 0x54f100, layout compacto): 0 Initialize | 1 Open (8 bytes -> handle) |
  2 Read ([0]=handle,[4]=max -> [0]=n, dados em +4) | 3 Write ([0]=handle,[4]=len, dados em +8 -> [0]=n) | 4 Close | 6 CarrierCheck | 7 Finish | 8 Reflush.
- `modem_connect_20` (0x19b800) manda cada linha do script AT + "\r\n" e REPETE ComWrite ate o retorno == len (retorno 0 = laco infinito);
  espera "OK" (aceita eco). Depois ATDT<numero do 6906>: espera "CONNECT" (trata "NO CARRIER", "BUSY"; timeout 3600 frames).
- Papel: `gp-22544` = 1 (quem disca) quando `gp-22540` == 0 (internet_to_modem @0x314b90). Com o 6902=1 o PS2 e sempre quem disca.
- Handshake em texto: chamador manda "\nPING\n" e re-manda "PING\n" ate 8 "PONG"; depois "START\n". Sync (`match_IO_sync` 0x19c460): "\nREADY\n" -> "OK" -> "START\n".
- Luta: pacotes de 20 bytes por frame (read_out 0x19c710 / read_in 0x19c8c0). Little-endian, campos a cada 4 bytes:
  +0 entrada A (u16) | +4 entrada B | +8 (byte baixo = tipo de controle; bit 0x10 = dado extra; byte alto = flags) | +12 frame (6 bits, comeca em 1) | resto 0.
  Em lockstep: o frame do oponente tem que ser exatamente o esperado ou o jogo marca erro de sincronia (gp-22460). Janela de atraso ~ (0x4a1... + 2) frames.
  match_IO_get (0x19cc00) calcula bordas de subida/descida (entradas ativas em 1).
- O contador `usb:`/`acc:` do heartbeat da v0.3 era dos despachantes NAO registrados do avewrap (sempre 0): nao provava nada.
