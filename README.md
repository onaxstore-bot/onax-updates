# ONAX TechMiner 0.4.2 — descoberta CJ

O atalho existente ONAX - Consultar CJ passa a ativar a descoberta de produtos CJ no Windows. Na primeira execução, pede a API Key em campo oculto e explica seu armazenamento cifrado por DPAPI para a conta atual do Windows. A chave só é salva depois de aceita pela CJ. Nenhuma chave entra no repositório ou nos relatórios.

Configura ONAX-Mineracao no Agendador de Tarefas, na sessão interativa do usuário, ao entrar no Windows e a cada 6 horas. A ativação faz a primeira rodada. Falhas no agendamento são informadas e não são tratadas como sucesso. Sem acesso remoto ao HP: execução real precisa ser confirmada pelo titular.

Pesquisa 6 termos em diferentes categorias, uma página de 5 resultados por termo; deduplica produtos e analisa uma variante de até 12 produtos. Consulta produto, estoque e cotação preliminar CN → US. Interrompe na primeira falha de fornecedor, sem repetir chamadas automaticamente dentro da rodada. Seis horas é um intervalo de execução, não garantia de que o Windows executará pontualmente: computador ligado, internet e usuário conectado são necessários.

Relatórios locais: %LOCALAPPDATA%/ONAX/data/mineracao_cj.json e mineracao_cj.html. O atalho abre o relatório no navegador normal, sem upload. Uma nova execução do atalho usa a credencial local, sem pedir chave novamente.

Limites: análise inicial CJ para EUA. Estoque de fábrica não é estoque pronto CJ. Menor frete é preliminar. Limites inferiores de preço usam apenas produto e frete, ads de 5%, reserva de 2% e cenários de margem sobre a venda de 30% e 50%. Não incluem taxas, tributos, câmbio, devoluções ou custos fixos; não representam lucro verificado. Sem demanda e comparação exata com concorrentes, candidatos continuam pendentes. Nenhum produto é comprado ou publicado.

Amazon, AliExpress, Alibaba e Shopee estão marcadas como conexões pendentes. Europa e Brasil não estão sendo cotados nesta rodada. A integração com Shopify e aprovação automática de produtos não foi ativada.

Não reinstalar: o controlador 0.3.1 existente pode aplicar esta versão assinada.

Referências: https://developers.cjdropshipping.com/en/api/api2/api/product.html ; https://developers.cjdropshipping.com/en/api/api2/api/auth.html ; https://learn.microsoft.com/en-us/windows/win32/seccrypto/example-c-program-using-cryptprotectdata

A análise intercala as categorias para distribuir o limite de 12 produtos entre os seis termos pesquisados.

O agendamento também tem um início por horário em seis horas após a ativação, para funcionar sem precisar sair e entrar novamente no Windows.
