import argparse
import sys
import warnings

import pandas as pd

INPUT_FILE = r'C:\Auto\sales.csv'
OUTPUT_FILE = r'C:\Auto\daily_by_sku.csv'

COLS = ['order_id', 'order_date', 'sku', 'quantity', 'price', 'status']

warnings.filterwarnings('ignore', message='Could not infer format')


def normalize_date(raw: str) -> str:
    """ISO-дата (YYYY-MM-DD), иначе исходная строка — день не теряем."""
    s = (raw or '').replace('\u00a0', ' ').strip()
    if not s:
        return ''
    try:
        return pd.to_datetime(s, format='%Y-%m-%d').strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        pass
    try:
        return pd.to_datetime(s, errors='raise').strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return s


def main():
    ap = argparse.ArgumentParser(description='Daily sales by SKU')
    ap.add_argument('--input', default=INPUT_FILE)
    ap.add_argument('--output', default=OUTPUT_FILE)
    ap.add_argument(
        '--sep', default=';',
        help="Разделитель CSV: ';' — для русского Excel (по умолчанию), ',' — для остальных"
    )
    ap.add_argument(
        '--decimal', default=',',
        help="Десятичный разделитель: ',' — для русского Excel (по умолчанию), '.' — для остальных"
    )
    args = ap.parse_args()

    # --- Чтение ---
    df = pd.read_csv(args.input, dtype=str, keep_default_na=False, encoding='utf-8-sig')

    for col in COLS:
        df[col] = df[col].str.replace('\u00a0', ' ', regex=False).str.strip()
    df = df[(df[COLS] != '').any(axis=1)].copy()

    df['status'] = df['status'].str.lower().replace({'canceled': 'cancelled'})
    df['date_norm'] = df['order_date'].apply(normalize_date)

    # Дедуп по order_id, приоритет — строке с валидной ISO-датой.
    df['_date_ok'] = df['date_norm'].str.match(r'^\d{4}-\d{2}-\d{2}$').astype(int)
    df = (
        df.sort_values('_date_ok', ascending=False)
          .drop_duplicates(subset=['order_id'], keep='first')
          .drop(columns=['_date_ok'])
          .reset_index(drop=True)
    )

    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce')
    df['price'] = pd.to_numeric(df['price'], errors='coerce')

    eligible = (
        (df['status'] == 'delivered')
        & df['quantity'].notna() & (df['quantity'] > 0)
        & df['price'].notna() & (df['price'] >= 0)
    )
    df['revenue'] = 0.0
    df.loc[eligible, 'revenue'] = df.loc[eligible, 'quantity'] * df.loc[eligible, 'price']

    lost_no_sku = int((df['sku'] == '').sum())
    df = df[df['sku'] != ''].copy()

    grouped = (
        df.groupby(['sku', 'date_norm'], as_index=False)
          .agg(orders=('order_id', 'nunique'), revenue=('revenue', 'sum'))
          .rename(columns={'date_norm': 'order_date'})
    )

    # --- Разбиение даты на year / month / day ---
    parts = grouped['order_date'].str.extract(r'^(\d{4})-(\d{2})-(\d{2})$')
    parts.columns = ['year', 'month', 'day']

    # Для строк с нераспознанной датой оставляем пустые year/month/day.
    for c in ('year', 'month', 'day'):
        parts[c] = parts[c].where(parts[c].notna(), '').astype(str).str.replace(r'\.0$', '', regex=True)

    result = pd.concat([grouped[['sku']], parts, grouped[['orders', 'revenue']]], axis=1)

    # Сортировка: sku, year, month, day; пустые даты — в конце.
    result['_sort_date'] = grouped['order_date']
    result = result.sort_values(['sku', '_sort_date']).drop(columns=['_sort_date'])
    result = result.reset_index(drop=True)

    result['revenue'] = result['revenue'].round(2)

    # --- Запись с ; и , (русский Excel) ---
    result.to_csv(
        args.output,
        index=False,
        sep=args.sep,
        decimal=args.decimal,
        encoding='utf-8-sig',  # BOM — Excel корректно распознаёт UTF-8
    )

    # --- Диагностика ---
    pairs_in_data = set(zip(df['sku'], df['date_norm']))
    pairs_in_out = set(
        zip(
            result['sku'],
            result.apply(
                lambda r: f"{r['year']}-{str(r['month']).zfill(2)}-{str(r['day']).zfill(2)}"
                if str(r['year']) else '',
                axis=1,
            ),
        )
    )
    missing = pairs_in_data - pairs_in_out

    print(f"Saved {len(result)} rows to {args.output}")
    print(f"  Separator: '{args.sep}'   Decimal: '{args.decimal}'   Encoding: utf-8-sig")
    print(f"  Columns:   {list(result.columns)}")
    print(f"  Unique (sku, day) pairs in data: {len(pairs_in_data)}")
    print(f"  Unique order_ids in data:        {df['order_id'].nunique()}")
    print(f"  Total revenue:                   {result['revenue'].sum():.2f}")
    print(f"  Rows dropped due to empty sku:   {lost_no_sku}")
    if missing:
        print(f"  WARNING: {len(missing)} (sku, day) pairs lost:", file=sys.stderr)
        for p in list(missing)[:20]:
            print(f"    {p}", file=sys.stderr)
    else:
        print("  OK: all (sku, day) pairs from data are present in output.")


if __name__ == '__main__':
    main()