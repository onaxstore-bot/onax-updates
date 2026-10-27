"""Run one CJ quote check. Never publishes or purchases."""
import argparse
import getpass
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from cj_client import CJClient, CJError


def save_report(path, report):
    """Replace a report only after a complete write, preserving a previous report on failure."""
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix='.onax-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_key():
    if os.name != 'nt':
        return getpass.getpass('Chave CJ (entrada oculta, somente nesta execução): ')
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except ImportError:
        raise CJError('Tcl/Tk ausente. Inclua Tcl/Tk na instalacao do Python.') from None
    try:
        root = tk.Tk()
    except (RuntimeError, tk.TclError):
        raise CJError('Nao foi possivel abrir o campo de senha. Verifique se Tcl/Tk foi instalado com o Python.') from None
    try:
        root.withdraw()
        root.attributes('-topmost', True)
        value = simpledialog.askstring('ONAX - acesso CJ',
            'Cole a API Key copiada pelo icone da CJ usando Ctrl+V.\n'
            'Os asteriscos confirmam a colagem. A chave nao sera salva.',
            parent=root, show='*')
        if value is None:
            raise CJError('Entrada cancelada. Nenhuma consulta enviada.')
        return value
    finally:
        root.destroy()


def main():
    parser = argparse.ArgumentParser(description='Consulta CJ: produto, estoque e fretes preliminares.')
    parser.add_argument('--sku', default='CJXFLPJY00201-Black')
    parser.add_argument('--destino', default='US')
    parser.add_argument('--origem', default='CN')
    parser.add_argument('--cep')
    parser.add_argument('--saida', default='cotacao_cj.json')
    parser.add_argument('--testar-acesso', action='store_true', help='Testar somente autenticacao CJ, sem consultar produtos.')
    args = parser.parse_args()
    try:
        key = os.environ.get('CJ_API_KEY') or read_key()
        client = CJClient(key)
        if args.testar_acesso:
            client.authenticate()
            print('ACESSO CJ CONFIRMADO. Chave aceita; nenhum produto consultado e nenhuma compra enviada.')
            return 0
        product = client.product(args.sku)
        variants = product.get('variants', []) if isinstance(product, dict) else []
        if not isinstance(variants, list) or any(not isinstance(v, dict) for v in variants):
            raise CJError('Resposta de variantes inválida. Nenhuma cotação gerada.')
        matching = [v for v in variants if v.get('variantSku') == args.sku]
        if len(matching) != 1 or not matching[0].get('vid'):
            raise CJError('SKU sem correspondência única. Não usar preço de outra variante.')
        variant = matching[0]
        stocks = client.stock(args.sku)
        quotes = client.freight(variant['vid'], args.destino, args.origem, zip_code=args.cep)
        report = {'queried_at': datetime.now(timezone.utc).isoformat(), 'sku': args.sku,
                  'variant_id': variant['vid'], 'product_price_usd_unvalidated': variant.get('variantSellPrice'),
                  'stock_response': stocks, 'shipping_quotes': quotes,
                  'publish_allowed': False, 'purchase_allowed': False,
                  'pending': ['custo total', 'taxas e tributos', 'demanda e concorrência',
                              'frete preciso por endereço', 'estoque por rota', 'lucro aprovado']}
        save_report(args.saida, report)
        print('Consulta salva em %s. Nenhuma compra ou publicação executada.' % args.saida)
        return 0
    except CJError as exc:
        print(str(exc))
        return 1
    except OSError:
        print('Não foi possível salvar o relatório. Confira a pasta de destino; nenhum pedido foi enviado.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
