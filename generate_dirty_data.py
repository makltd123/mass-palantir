import random
from datetime import datetime, timedelta
import pandas as pd
from faker import Faker

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
# КЛЮЧ ОТВЕТОВ (для консоли)
# ==========================================================

answer_key = {
    "renamed_fields": {},
    "duplicate_customers": [],
    "typos": [],
    "date_formats": {},
    "similar_products": []
}


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
# 3.1 ДУБЛИ КЛИЕНТОВ
# ==========================================================

duplicate_source_ids = random.sample(
    customers["id"].tolist(),
    4
)

next_customer_id = customers["id"].max() + 1


for source_id in duplicate_source_ids:

    original = customers[
        customers["id"] == source_id
    ].iloc[0]

    variants = [
        original["company_name"].lower(),
        original["company_name"].replace('"', '«').replace('"', '»'),
        original["company_name"].replace("ООО ", ""),
        original["company_name"].replace(
            "ООО ",
            ""
        ) + " ООО"
    ]

    duplicate = {
        "id": next_customer_id,
        "company_name": random.choice(variants),
        "city": original["city"],
        "email": original["email"]
    }

    customers = pd.concat(
        [
            customers,
            pd.DataFrame([duplicate])
        ],
        ignore_index=True
    )

    answer_key["duplicate_customers"].append(
        {
            "duplicate_id": next_customer_id,
            "original_id": source_id
        }
    )

    next_customer_id += 1



# ==========================================================
# 3.2 ОПЕЧАТКИ В НАЗВАНИЯХ КЛИЕНТОВ
# ==========================================================

def make_typo(text):

    if len(text) < 5:
        return text

    pos = random.randint(1, len(text)-2)

    mode = random.choice(
        ["swap", "delete"]
    )

    chars = list(text)

    if mode == "swap":
        chars[pos], chars[pos+1] = (
            chars[pos+1],
            chars[pos]
        )

    else:
        chars.pop(pos)

    return "".join(chars)



customer_typo_rows = random.sample(
    customers.index.tolist(),
    5
)


for idx in customer_typo_rows:

    old = customers.loc[
        idx,
        "company_name"
    ]

    customers.loc[
        idx,
        "company_name"
    ] = make_typo(old)

    answer_key["typos"].append(
        {
            "file": "customers.csv",
            "row": int(idx),
            "field": "company_name"
        }
    )


# ==========================================================
# 4. CONTACTS
# ==========================================================

contacts_data = []

contact_id = 1

customer_ids = customers["id"].tolist()


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
# 5.1 ПОХОЖИЕ, НО РАЗНЫЕ ТОВАРЫ
# ==========================================================

extra_products = [
    {
        "category_id": 1,
        "product_name": "Двигатель ДВС-240",
        "stock_quantity": 75,
        "warehouse_id": 1
    },
    {
        "category_id": 1,
        "product_name": "Двигатель ДВС-240М",
        "stock_quantity": 60,
        "warehouse_id": 2
    },
    {
        "category_id": 2,
        "product_name": "Насос Н-200",
        "stock_quantity": 40,
        "warehouse_id": 1
    },
    {
        "category_id": 2,
        "product_name": "Насос Н-200А",
        "stock_quantity": 35,
        "warehouse_id": 3
    }
]


for item in extra_products:

    inventory = pd.concat(
        [
            inventory,
            pd.DataFrame(
                [{
                    "id": inventory["id"].max() + 1,
                    **item
                }]
            )
        ],
        ignore_index=True
    )


similar_pairs = []

for name in [
    ("Двигатель ДВС-240", "Двигатель ДВС-240М"),
    ("Насос Н-200", "Насос Н-200А")
]:

    ids = inventory[
        inventory["product_name"].isin(name)
    ]["id"].tolist()

    similar_pairs.append(
        {
            "names": name,
            "ids": ids
        }
    )


answer_key["similar_products"] = similar_pairs



# ==========================================================
# 5.2 ОПЕЧАТКИ В PRODUCT_NAME
# ==========================================================

inventory_typo_rows = random.sample(
    inventory.index.tolist(),
    5
)


for idx in inventory_typo_rows:

    old = inventory.loc[
        idx,
        "product_name"
    ]

    inventory.loc[
        idx,
        "product_name"
    ] = make_typo(old)

    answer_key["typos"].append(
        {
            "file": "inventory.csv",
            "row": int(idx),
            "field": "product_name"
        }
    )



# ==========================================================
# 6. SUPPLIERS
# ==========================================================

suppliers_data = []

used_suppliers = set()


for i in range(1, NUM_SUPPLIERS + 1):

    while True:

        name = (
            f'АО "{fake.last_name()} '
            f'{random.choice(company_suffix)}"'
        )

        if name not in used_suppliers:
            used_suppliers.add(name)
            break


    suppliers_data.append({
        "id": i,
        "supplier_name": name,
        "country": random.choice(
            supplier_countries
        ),
        "email": fake.company_email()
    })


suppliers = pd.DataFrame(
    suppliers_data
)



# ==========================================================
# 7. SUPPLIER CONTRACTS
# ==========================================================

contracts = []


for i in range(1, NUM_SUPPLIER_CONTRACTS + 1):

    contracts.append({

        "id": i,

        "supplier_id":
            random.choice(
                suppliers["id"].tolist()
            ),

        "product_category_id":
            random.choice(
                product_categories["id"].tolist()
            ),

        "delivery_terms":
            random.choice(
                delivery_terms
            ),

        "delivery_days":
            random.randint(5, 45)

    })


supplier_contracts = pd.DataFrame(
    contracts
)



# ==========================================================
# 8. ORDERS
# ==========================================================

orders_data = []

start_date = datetime(2024, 1, 1)


date_format_counter = {
    "YYYY-MM-DD": 0,
    "DD.MM.YYYY": 0
}


for i in range(1, NUM_ORDERS + 1):

    current_date = (
        start_date
        +
        timedelta(
            days=random.randint(0, 500)
        )
    )


    if random.random() < 0.7:

        formatted_date = (
            current_date.strftime(
                "%Y-%m-%d"
            )
        )

        date_format_counter[
            "YYYY-MM-DD"
        ] += 1


    else:

        formatted_date = (
            current_date.strftime(
                "%d.%m.%Y"
            )
        )

        date_format_counter[
            "DD.MM.YYYY"
        ] += 1



    orders_data.append({

        "id": i,

        "customer_id":
            random.choice(
                customer_ids
            ),

        "order_date":
            formatted_date,

        "status":
            random.choice(
                order_statuses
            )

    })


orders = pd.DataFrame(
    orders_data
)


answer_key["date_formats"] = date_format_counter



# ==========================================================
# 8.1 МУСОРНЫЙ СТОЛБЕЦ STATUS_OLD_V1
# ==========================================================

orders["status_old_v1"] = [
    random.choice(
        [
            "X1",
            "Y2",
            "Z0",
            ""
        ]
    )
    for _ in range(len(orders))
]



# ==========================================================
# 9. ORDER ITEMS
# ==========================================================

order_items_data = []


for i in range(1, NUM_ORDER_ITEMS + 1):

    order_items_data.append({

        "id": i,

        "order_id":
            random.choice(
                orders["id"].tolist()
            ),

        "inventory_id":
            random.choice(
                inventory["id"].tolist()
            ),

        "quantity":
            random.randint(1, 15)

    })


order_items = pd.DataFrame(
    order_items_data
)



# ==========================================================
# 10. PURCHASE REQUESTS
# ==========================================================

purchase_requests_data = []


for i in range(1, NUM_PURCHASE_REQUESTS + 1):

    purchase_requests_data.append({

        "id": i,

        "inventory_id":
            random.choice(
                inventory["id"].tolist()
            ),

        "supplier_id":
            random.choice(
                suppliers["id"].tolist()
            ),

        "quantity":
            random.randint(5, 120),

        "request_date":
            (
                start_date
                +
                timedelta(
                    days=random.randint(0, 500)
                )
            ).date(),

        "status":
            random.choice(
                purchase_statuses
            )

    })


purchase_requests = pd.DataFrame(
    purchase_requests_data
)



# ==========================================================
# ПРОПУСКИ
# ==========================================================

# customers.email

for idx in random.sample(
    customers.index.tolist(),
    3
):

    customers.loc[
        idx,
        "email"
    ] = ""


# contacts.phone

for idx in random.sample(
    contacts.index.tolist(),
    5
):

    contacts.loc[
        idx,
        "phone"
    ] = ""



# ==========================================================
# МУСОРНЫЙ СТОЛБЕЦ FLAG_2
# ==========================================================

customers["flag_2"] = [
    random.choice(
        [
            "A",
            "B",
            "",
            "X"
        ]
    )
    for _ in range(len(customers))
]



# ==========================================================
# ПЕРЕИМЕНОВАНИЯ LEGACY-ПОЛЕЙ
# ==========================================================

customers = customers.rename(
    columns={
        "id": "f_17"
    }
)

orders = orders.rename(
    columns={
        "customer_id": "ref_9"
    }
)

inventory = inventory.rename(
    columns={
        "id": "sku_code"
    }
)

order_items = order_items.rename(
    columns={
        "inventory_id": "item_ref"
    }
)


answer_key["renamed_fields"] = {

    "customers.f_17":
        "старое поле id",

    "orders.ref_9":
        "старое поле customer_id",

    "inventory.sku_code":
        "старое поле id",

    "order_items.item_ref":
        "старое поле inventory_id"

}
# ==========================================================
# СОХРАНЕНИЕ CSV
# ==========================================================

customers.to_csv(
    "customers.csv",
    index=False,
    encoding="utf-8-sig"
)

contacts.to_csv(
    "contacts.csv",
    index=False,
    encoding="utf-8-sig"
)

product_categories.to_csv(
    "product_categories.csv",
    index=False,
    encoding="utf-8-sig"
)

inventory.to_csv(
    "inventory.csv",
    index=False,
    encoding="utf-8-sig"
)

warehouses.to_csv(
    "warehouses.csv",
    index=False,
    encoding="utf-8-sig"
)

suppliers.to_csv(
    "suppliers.csv",
    index=False,
    encoding="utf-8-sig"
)

supplier_contracts.to_csv(
    "supplier_contracts.csv",
    index=False,
    encoding="utf-8-sig"
)

orders.to_csv(
    "orders.csv",
    index=False,
    encoding="utf-8-sig"
)

order_items.to_csv(
    "order_items.csv",
    index=False,
    encoding="utf-8-sig"
)

purchase_requests.to_csv(
    "purchase_requests.csv",
    index=False,
    encoding="utf-8-sig"
)



print(
    "CSV-файлы успешно сохранены."
)



# ==========================================================
# ПРОВЕРКА ЦЕЛОСТНОСТИ СВЯЗЕЙ
# ==========================================================

def check_fk(
    child_df,
    child_name,
    fk_column,
    parent_df,
    parent_name,
    parent_key="id"
):

    parent_ids = set(
        parent_df[parent_key]
    )

    wrong = child_df.loc[
        ~child_df[fk_column].isin(parent_ids)
    ]


    if wrong.empty:

        print(
            f"✓ {child_name}.{fk_column} -> "
            f"{parent_name}.{parent_key}"
        )

        return []


    errors = []

    for _, row in wrong.iterrows():

        errors.append(
            f"{child_name}: "
            f"запись id={row['id']} "
            f"содержит неверный "
            f"{fk_column}={row[fk_column]}"
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
            "customers",
            "f_17"
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
            "ref_9",
            customers,
            "customers",
            "f_17"
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
            "item_ref",
            inventory,
            "inventory",
            "sku_code"
        )
    )


    errors.extend(
        check_fk(
            purchase_requests,
            "purchase_requests",
            "inventory_id",
            inventory,
            "inventory",
            "sku_code"
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

        print(
            "✅ Все связи корректны."
        )

    else:

        print(
            "❌ Обнаружены ошибки:"
        )

        for err in errors:
            print(
                "-",
                err
            )



# ==========================================================
# ФИНАЛЬНЫЙ КЛЮЧ ОТВЕТОВ
# ==========================================================

def print_answer_key():

    print("\n")
    print("=" * 60)
    print("КЛЮЧ ОТВЕТОВ: ВНЕСЁННАЯ ГРЯЗЬ")
    print("=" * 60)



    print("\n1. ПЕРЕИМЕНОВАННЫЕ ПОЛЯ:")

    for k, v in answer_key["renamed_fields"].items():

        print(
            f"  {k} <- {v}"
        )



    print("\n2. ДУБЛИ КЛИЕНТОВ:")

    for item in answer_key["duplicate_customers"]:

        print(
            f"  duplicate id={item['duplicate_id']} "
            f"<- original id={item['original_id']}"
        )



    print("\n3. ОПЕЧАТКИ:")

    for typo in answer_key["typos"]:

        print(
            f"  {typo['file']} | "
            f"строка {typo['row']} | "
            f"поле {typo['field']}"
        )



    print("\n4. ФОРМАТЫ ДАТ orders.order_date:")

    for fmt, count in answer_key["date_formats"].items():

        print(
            f"  {fmt}: {count} строк"
        )



    print("\n5. ПОХОЖИЕ, НО РАЗНЫЕ ТОВАРЫ:")

    for pair in answer_key["similar_products"]:

        print(
            f"  {pair['names'][0]} "
            f"(id={pair['ids'][0]})"
        )

        print(
            f"  {pair['names'][1]} "
            f"(id={pair['ids'][1]})"
        )

        print(
            "  НЕ объединять — разные товары"
        )



    print("=" * 60)



# ==========================================================
# ЗАПУСК
# ==========================================================

check_integrity()

print_answer_key()
