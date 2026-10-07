import argparse
import os
import random
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker

# Куда писать CSV: все записи ниже идут относительными путями.
_parser = argparse.ArgumentParser(description="Генератор чистых данных.")
_parser.add_argument("--out-dir", default=".", help="каталог для CSV-файлов")
_args = _parser.parse_args()
os.makedirs(_args.out_dir, exist_ok=True)
os.chdir(_args.out_dir)

fake = Faker("ru_RU")
random.seed(42)
Faker.seed(42)

# ==========================================================
# НАСТРОЙКИ
# ==========================================================

NUM_CUSTOMERS = 25
NUM_CONTACTS = 35
NUM_CATEGORIES = 5
NUM_WAREHOUSES = 3
NUM_INVENTORY = 20
NUM_SUPPLIERS = 10
NUM_SUPPLIER_CONTRACTS = 15
NUM_ORDERS = 60
NUM_ORDER_ITEMS = 150
NUM_PURCHASE_REQUESTS = 20

# ==========================================================
# СПРАВОЧНИКИ
# ==========================================================

product_categories_list = [
    "Двигатели",
    "Насосы",
    "Турбокомпрессоры",
    "Редукторы",
    "Комплектующие",
]

warehouse_names = [
    ("Основной склад", "Москва"),
    ("Производственный склад", "Санкт-Петербург"),
    ("Региональный склад", "Екатеринбург"),
]

supplier_countries = [
    "Россия",
    "Германия",
    "Китай",
    "Италия",
    "Турция",
]

order_statuses = [
    "Новый",
    "В работе",
    "Производство",
    "Отгружен",
    "Закрыт",
]

purchase_statuses = [
    "Создана",
    "Отправлена",
    "Подтверждена",
    "Получена",
]

delivery_terms = [
    "FCA",
    "FOB",
    "CIF",
    "DAP",
    "EXW",
]

company_suffix = [
    "Инжиниринг",
    "Пром",
    "Тех",
    "Механика",
    "Сервис",
    "Системы",
    "Маш",
]

inventory_names = {
    "Двигатели": [
        "Двигатель Д-100",
        "Двигатель Д-200",
        "Двигатель Д-300",
        "Двигатель Д-500",
    ],
    "Насосы": [
        "Насос Н-10",
        "Насос Н-20",
        "Насос Н-40",
        "Насос высокого давления",
    ],
    "Турбокомпрессоры": [
        "Турбокомпрессор ТК-1",
        "Турбокомпрессор ТК-2",
        "Турбокомпрессор ТК-5",
        "Турбокомпрессор Heavy",
    ],
    "Редукторы": [
        "Редуктор Р-80",
        "Редуктор Р-120",
        "Редуктор Р-200",
        "Редуктор промышленный",
    ],
    "Комплектующие": [
        "Вал приводной",
        "Комплект уплотнений",
        "Подшипниковый узел",
        "Муфта соединительная",
    ],
}

positions = [
    "Главный инженер",
    "Руководитель закупок",
    "Менеджер проекта",
    "Технический директор",
    "Начальник производства",
    "Специалист по снабжению",
]

# ==========================================================
# 1. PRODUCT CATEGORIES
# ==========================================================

product_categories = pd.DataFrame({
    "id": range(1, NUM_CATEGORIES + 1),
    "category_name": product_categories_list
})

# ==========================================================
# 2. WAREHOUSES
# ==========================================================

warehouses = pd.DataFrame({
    "id": range(1, NUM_WAREHOUSES + 1),
    "warehouse_name": [x[0] for x in warehouse_names],
    "city": [x[1] for x in warehouse_names],
    "capacity": [5000, 7000, 3500]
})

# ==========================================================
# 3. CUSTOMERS
# ==========================================================

customers_data = []

used_names = set()

for i in range(1, NUM_CUSTOMERS + 1):

    while True:
        name = f'ООО "{fake.last_name()} {random.choice(company_suffix)}"'
        if name not in used_names:
            used_names.add(name)
            break

    customers_data.append({
        "id": i,
        "company_name": name,
        "city": fake.city(),
        "email": fake.company_email()
    })

customers = pd.DataFrame(customers_data)

# ==========================================================
# 4. CONTACTS
# ==========================================================

contacts_data = []

contact_id = 1

customer_ids = list(customers["id"])

# сначала по одному контакту каждому
for cid in customer_ids:
    contacts_data.append({
        "id": contact_id,
        "customer_id": cid,
        "name": fake.name(),
        "phone": fake.phone_number(),
        "position": random.choice(positions)
    })
    contact_id += 1

while len(contacts_data) < NUM_CONTACTS:
    cid = random.choice(customer_ids)
    contacts_data.append({
        "id": contact_id,
        "customer_id": cid,
        "name": fake.name(),
        "phone": fake.phone_number(),
        "position": random.choice(positions)
    })
    contact_id += 1

contacts = pd.DataFrame(contacts_data)

# ==========================================================
# 5. INVENTORY
# ==========================================================

inventory_data = []

inventory_id = 1

warehouse_ids = warehouses["id"].tolist()

for category in product_categories.itertuples():

    for product in inventory_names[category.category_name]:

        if inventory_id > NUM_INVENTORY:
            break

        inventory_data.append({
            "id": inventory_id,
            "category_id": category.id,
            "product_name": product,
            "stock_quantity": random.randint(5, 250),
            "warehouse_id": random.choice(warehouse_ids)
        })

        inventory_id += 1

inventory = pd.DataFrame(inventory_data)

# ==========================================================
# 6. SUPPLIERS
# ==========================================================

suppliers_data = []

used_suppliers = set()

for i in range(1, NUM_SUPPLIERS + 1):

    while True:
        name = f'АО "{fake.last_name()} {random.choice(company_suffix)}"'
        if name not in used_suppliers:
            used_suppliers.add(name)
            break

    suppliers_data.append({
        "id": i,
        "supplier_name": name,
        "country": random.choice(supplier_countries),
        "email": fake.company_email()
    })

suppliers = pd.DataFrame(suppliers_data)

# ==========================================================
# 7. SUPPLIER CONTRACTS
# ==========================================================

contracts = []

for i in range(1, NUM_SUPPLIER_CONTRACTS + 1):
    contracts.append({
        "id": i,
        "supplier_id": random.choice(suppliers["id"].tolist()),
        "product_category_id": random.choice(product_categories["id"].tolist()),
        "delivery_terms": random.choice(delivery_terms),
        "delivery_days": random.randint(5, 45)
    })

supplier_contracts = pd.DataFrame(contracts)

# ==========================================================
# 8. ORDERS
# ==========================================================

orders_data = []

start_date = datetime(2024, 1, 1)

for i in range(1, NUM_ORDERS + 1):
    orders_data.append({
        "id": i,
        "customer_id": random.choice(customer_ids),
        "order_date": (
            start_date + timedelta(days=random.randint(0, 500))
        ).date(),
        "status": random.choice(order_statuses)
    })

orders = pd.DataFrame(orders_data)

# ==========================================================
# 9. ORDER ITEMS
# ==========================================================

order_items_data = []

for i in range(1, NUM_ORDER_ITEMS + 1):
    order_items_data.append({
        "id": i,
        "order_id": random.choice(orders["id"].tolist()),
        "inventory_id": random.choice(inventory["id"].tolist()),
        "quantity": random.randint(1, 15)
    })

order_items = pd.DataFrame(order_items_data)

# ==========================================================
# 10. PURCHASE REQUESTS
# ==========================================================

purchase_requests_data = []

for i in range(1, NUM_PURCHASE_REQUESTS + 1):
    purchase_requests_data.append({
        "id": i,
        "inventory_id": random.choice(inventory["id"].tolist()),
        "supplier_id": random.choice(suppliers["id"].tolist()),
        "quantity": random.randint(5, 120),
        "request_date": (
            start_date + timedelta(days=random.randint(0, 500))
        ).date(),
        "status": random.choice(purchase_statuses)
    })

purchase_requests = pd.DataFrame(purchase_requests_data)

# ==========================================================
# СОХРАНЕНИЕ CSV
# ==========================================================

customers.to_csv("customers.csv", index=False, encoding="utf-8-sig")
contacts.to_csv("contacts.csv", index=False, encoding="utf-8-sig")
product_categories.to_csv("product_categories.csv", index=False, encoding="utf-8-sig")
inventory.to_csv("inventory.csv", index=False, encoding="utf-8-sig")
warehouses.to_csv("warehouses.csv", index=False, encoding="utf-8-sig")
suppliers.to_csv("suppliers.csv", index=False, encoding="utf-8-sig")
supplier_contracts.to_csv("supplier_contracts.csv", index=False, encoding="utf-8-sig")
orders.to_csv("orders.csv", index=False, encoding="utf-8-sig")
order_items.to_csv("order_items.csv", index=False, encoding="utf-8-sig")
purchase_requests.to_csv("purchase_requests.csv", index=False, encoding="utf-8-sig")

print("CSV-файлы успешно сохранены.")

# ==========================================================
# ПРОВЕРКА ЦЕЛОСТНОСТИ СВЯЗЕЙ
# ==========================================================

def check_fk(child_df, child_name, fk_column, parent_df, parent_name, parent_key="id"):
    parent_ids = set(parent_df[parent_key])
    wrong = child_df.loc[~child_df[fk_column].isin(parent_ids)]

    if wrong.empty:
        print(f"✓ {child_name}.{fk_column} -> {parent_name}.{parent_key}")
        return []

    errors = []
    for _, row in wrong.iterrows():
        errors.append(
            f"{child_name}: запись id={row['id']} содержит неверный {fk_column}={row[fk_column]}"
        )
    return errors


def check_integrity():

    print("\n==============================")
    print("ПРОВЕРКА ЦЕЛОСТНОСТИ СВЯЗЕЙ")
    print("==============================")

    errors = []

    errors.extend(
        check_fk(
            contacts,
            "contacts",
            "customer_id",
            customers,
            "customers"
        )
    )

    errors.extend(
        check_fk(
            inventory,
            "inventory",
            "category_id",
            product_categories,
            "product_categories"
        )
    )

    errors.extend(
        check_fk(
            inventory,
            "inventory",
            "warehouse_id",
            warehouses,
            "warehouses"
        )
    )

    errors.extend(
        check_fk(
            supplier_contracts,
            "supplier_contracts",
            "supplier_id",
            suppliers,
            "suppliers"
        )
    )

    errors.extend(
        check_fk(
            supplier_contracts,
            "supplier_contracts",
            "product_category_id",
            product_categories,
            "product_categories"
        )
    )

    errors.extend(
        check_fk(
            orders,
            "orders",
            "customer_id",
            customers,
            "customers"
        )
    )

    errors.extend(
        check_fk(
            order_items,
            "order_items",
            "order_id",
            orders,
            "orders"
        )
    )

    errors.extend(
        check_fk(
            order_items,
            "order_items",
            "inventory_id",
            inventory,
            "inventory"
        )
    )

    errors.extend(
        check_fk(
            purchase_requests,
            "purchase_requests",
            "inventory_id",
            inventory,
            "inventory"
        )
    )

    errors.extend(
        check_fk(
            purchase_requests,
            "purchase_requests",
            "supplier_id",
            suppliers,
            "suppliers"
        )
    )

    print()

    if not errors:
        print("✅ Все связи корректны.")
    else:
        print("❌ Обнаружены ошибки:")
        for err in errors:
            print("-", err)


# ==========================================================
# ЗАПУСК ПРОВЕРКИ
# ==========================================================

check_integrity()
