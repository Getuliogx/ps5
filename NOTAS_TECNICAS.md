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
