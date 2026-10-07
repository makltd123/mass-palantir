# Пример прогона без LLM на «грязных» данных

Как получен:

```bash
python generate_dirty_data.py --out-dir ./demo
python ontology_builder_v3.py --data-dir ./demo --no-llm --stock-threshold 40
```

`MISTRAL_API_KEY` не задан — все этапы выполнены эвристиками. Порог остатка
поднят до 40, потому что в синтетических данных нет позиций с остатком < 10.

Что видно в логе ниже:

- переименованные ключи найдены по значениям, а не по именам:
  `orders.ref_9 → customers.f_17`, `order_items.item_ref → inventory.sku_code`;
- мусорные столбцы `flag_2` и `status_old_v1` исключены, а короткие числовые
  ключи (`category_id`, `warehouse_id`) — нет;
- дубли клиентов: 4 из 4, без ложных срабатываний (precision и recall 100%);
- сверка с `answer_key.json`: 8 из 8 проверок пройдено.

```text
======================================================================
  ПРОТОТИП v3: DATA PROFILING + ДВУХШАГОВЫЕ ДУБЛИ
======================================================================
  Данные: /tmp/claude-0/-home-user-mass-palantir/3e6767ad-17b6-52c3-8497-782394c65c08/scratchpad/t5
  Таблиц найдено: 10
  LLM: отключена

======================================================================
  ЭТАП 1: Извлечение схем из CSV-файлов
======================================================================
  customers                : 5 столбцов, 29 строк
  contacts                 : 5 столбцов, 35 строк
  product_categories       : 2 столбцов, 5 строк
  inventory                : 5 столбцов, 24 строк
  warehouses               : 4 столбцов, 3 строк
  suppliers                : 4 столбцов, 10 строк
  supplier_contracts       : 5 столбцов, 15 строк
  orders                   : 5 столбцов, 60 строк
  order_items              : 4 столбцов, 150 строк
  purchase_requests        : 6 столбцов, 20 строк

======================================================================
  DATA PROFILING: Анализ значений во всех столбцах
======================================================================

  customers:
    f_17                      unique= 29/ 29  card=1.00  avg_len=  1.7  SEQ_INT
    company_name              unique= 29/ 29  card=1.00  avg_len= 21.2  
    city                      unique= 25/ 29  card=0.86  avg_len= 12.0  
    email                     unique= 22/ 29  card=0.76  avg_len= 20.9  EMPTY=3
    flag_2                    unique=  3/ 29  card=0.10  avg_len=  1.0  LIKELY_JUNK | EMPTY=8

  contacts:
    id                        unique= 35/ 35  card=1.00  avg_len=  1.7  SEQ_INT
    customer_id               unique= 29/ 35  card=0.83  avg_len=  1.7  SEQ_INT | FK→customers.f_17(29/29, ключей родителя 1.0)
    name                      unique= 35/ 35  card=1.00  avg_len= 25.4  
    phone                     unique= 30/ 35  card=0.86  avg_len= 14.9  EMPTY=5
    position                  unique=  6/ 35  card=0.17  avg_len= 18.5  

  product_categories:
    id                        unique=  5/  5  card=1.00  avg_len=  1.0  SEQ_INT
    category_name             unique=  5/  5  card=1.00  avg_len= 10.6  

  inventory:
    sku_code                  unique= 24/ 24  card=1.00  avg_len=  1.6  SEQ_INT
    category_id               unique=  5/ 24  card=0.21  avg_len=  1.0  SEQ_INT | FK→product_categories.id(5/5, ключей родителя 1.0)
    product_name              unique= 24/ 24  card=1.00  avg_len= 15.9  
    stock_quantity            unique= 24/ 24  card=1.00  avg_len=  2.5  
    warehouse_id              unique=  3/ 24  card=0.12  avg_len=  1.0  SEQ_INT | FK→warehouses.id(3/3, ключей родителя 1.0)

  warehouses:
    id                        unique=  3/  3  card=1.00  avg_len=  1.0  SEQ_INT
    warehouse_name            unique=  3/  3  card=1.00  avg_len= 18.0  
    city                      unique=  3/  3  card=1.00  avg_len= 11.0  
    capacity                  unique=  3/  3  card=1.00  avg_len=  4.0  

  suppliers:
    id                        unique= 10/ 10  card=1.00  avg_len=  1.1  SEQ_INT
    supplier_name             unique= 10/ 10  card=1.00  avg_len= 18.7  
    country                   unique=  5/ 10  card=0.50  avg_len=  6.1  
    email                     unique= 10/ 10  card=1.00  avg_len= 22.0  

  supplier_contracts:
    id                        unique= 15/ 15  card=1.00  avg_len=  1.4  SEQ_INT
    supplier_id               unique=  8/ 15  card=0.53  avg_len=  1.0  SEQ_INT | FK→suppliers.id(8/8, ключей родителя 0.8)
    product_category_id       unique=  5/ 15  card=0.33  avg_len=  1.0  SEQ_INT | FK→product_categories.id(5/5, ключей родителя 1.0)
    delivery_terms            unique=  5/ 15  card=0.33  avg_len=  3.0  
    delivery_days             unique= 13/ 15  card=0.87  avg_len=  1.9  

  orders:
    id                        unique= 60/ 60  card=1.00  avg_len=  1.9  SEQ_INT
    ref_9                     unique= 28/ 60  card=0.47  avg_len=  1.7  FK→customers.f_17(28/28, ключей родителя 0.966)
    order_date                unique= 59/ 60  card=0.98  avg_len= 10.0  DATE
    status                    unique=  5/ 60  card=0.08  avg_len=  7.5  
    status_old_v1             unique=  3/ 60  card=0.05  avg_len=  2.0  LIKELY_JUNK | EMPTY=14

  order_items:
    id                        unique=150/150  card=1.00  avg_len=  2.3  SEQ_INT
    order_id                  unique= 57/150  card=0.38  avg_len=  1.8  FK→orders.id(57/57, ключей родителя 0.95)
    item_ref                  unique= 24/150  card=0.16  avg_len=  1.6  SEQ_INT | FK→inventory.sku_code(24/24, ключей родителя 1.0)
    quantity                  unique= 15/150  card=0.10  avg_len=  1.4  SEQ_INT

  purchase_requests:
    id                        unique= 20/ 20  card=1.00  avg_len=  1.6  SEQ_INT
    inventory_id              unique= 13/ 20  card=0.65  avg_len=  1.6  FK→inventory.sku_code(13/13, ключей родителя 0.542)
    supplier_id               unique=  7/ 20  card=0.35  avg_len=  1.2  FK→suppliers.id(7/7, ключей родителя 0.7)
    quantity                  unique= 19/ 20  card=0.95  avg_len=  2.3  
    request_date              unique= 20/ 20  card=1.00  avg_len= 10.0  DATE
    status                    unique=  4/ 20  card=0.20  avg_len=  9.3  

  Роли столбцов:
    customers: name=company_name, pk=f_17
    contacts: customers_fk=customer_id, name=name, pk=id
    product_categories: name=category_name, pk=id
    inventory: name=product_name, pk=sku_code, product_categories_fk=category_id, warehouses_fk=warehouse_id
    warehouses: name=warehouse_name, pk=id
    suppliers: name=supplier_name, pk=id
    supplier_contracts: name=delivery_terms, pk=id, product_categories_fk=product_category_id, suppliers_fk=supplier_id
    orders: customers_fk=ref_9, name=status, pk=id
    order_items: inventory_fk=item_ref, orders_fk=order_id, pk=id
    purchase_requests: inventory_fk=inventory_id, name=status, pk=id, suppliers_fk=supplier_id

======================================================================
  ЭТАП 1.5: Классификация столбцов (с data profiling)
======================================================================
[Этап 1.5] LLM отключена (--no-llm), используем эвристику
  Источник: heuristic
  Business: 23, Keys: 20, Junk: 2
    МУСОР: customers.flag_2 — мало уникальных коротких значений
    МУСОР: orders.status_old_v1 — мало уникальных коротких значений
    КЛЮЧ:  customers.f_17 — последовательные целые числа, уникальны
    КЛЮЧ:  contacts.id — последовательные целые числа, уникальны
    КЛЮЧ:  contacts.customer_id — совпадает с customers.f_17
    КЛЮЧ:  product_categories.id — последовательные целые числа, уникальны
    КЛЮЧ:  inventory.sku_code — последовательные целые числа, уникальны
    КЛЮЧ:  inventory.category_id — совпадает с product_categories.id
    КЛЮЧ:  inventory.warehouse_id — совпадает с warehouses.id
    КЛЮЧ:  warehouses.id — последовательные целые числа, уникальны
    КЛЮЧ:  suppliers.id — последовательные целые числа, уникальны
    КЛЮЧ:  supplier_contracts.id — последовательные целые числа, уникальны
    КЛЮЧ:  supplier_contracts.supplier_id — совпадает с suppliers.id
    КЛЮЧ:  supplier_contracts.product_category_id — совпадает с product_categories.id
    КЛЮЧ:  orders.id — последовательные целые числа, уникальны
    КЛЮЧ:  orders.ref_9 — совпадает с customers.f_17
    КЛЮЧ:  order_items.id — последовательные целые числа, уникальны
    КЛЮЧ:  order_items.order_id — совпадает с orders.id
    КЛЮЧ:  order_items.item_ref — совпадает с inventory.sku_code
    КЛЮЧ:  purchase_requests.id — последовательные целые числа, уникальны
    КЛЮЧ:  purchase_requests.inventory_id — совпадает с inventory.sku_code
    КЛЮЧ:  purchase_requests.supplier_id — совпадает с suppliers.id

======================================================================
  ЭТАП 2: Построение графа сущностей
======================================================================
[Этап 2] LLM отключена (--no-llm), используем эвристику
  Источник: heuristic
  Сущностей: 10
    - customers: 4 атрибутов
    - contacts: 5 атрибутов
    - product_categories: 2 атрибутов
    - inventory: 5 атрибутов
    - warehouses: 4 атрибутов
    - suppliers: 4 атрибутов
    - supplier_contracts: 5 атрибутов
    - orders: 4 атрибутов
    - order_items: 4 атрибутов
    - purchase_requests: 6 атрибутов
  Связей: 10
  Совпадений полей: 20

======================================================================
  ЭТАП 2.5: Поиск дублей (двухшаговый)
======================================================================
  [Шаг 1] Нормализация + fuzzy matching...
  Кандидатов на дубли (score >= 0.85): 5
    id=18↔29: score=1.0, name_ratio=1.0, email=True, city=True
      "ООО "Андреев Инжиниринг"" vs ""Андреев Инжиниринг""
    id=23↔27: score=1.0, name_ratio=1.0, email=True, city=True
      "ООО "Денисова Сервис"" vs "ООО «Денисова Сервис«"
    id=21↔28: score=0.96, name_ratio=0.96, email=True, city=True
      "ООО "Журавлев Пром"" vs ""Журавлев Пом" ООО"
    id=7↔26: score=0.95, name_ratio=0.833, email=True, city=True
      "ООО "Савин Пром"" vs ""Савин Пром"ООО"
    id=3↔10: score=0.878, name_ratio=0.878, email=False, city=False
      "ООО "Куликова Инжиниринг"" vs "ООО "Калашникова Инжиниринг""

  [Шаг 2] Проверка 5 кандидатов...
[Этап 2.5-шаг2] LLM отключена (--no-llm), используем эвристику
  Источник подтверждения: heuristic

  Подтверждённых дублей: 4
    id=18↔29: high — совпадают email и город
    id=23↔27: high — совпадают email и город
    id=21↔28: high — совпадают email и город
    id=7↔26: high — совпадают email и город

======================================================================
  ЭТАП 3: Сохранение результатов
======================================================================
  Сохранено в /tmp/claude-0/-home-user-mass-palantir/3e6767ad-17b6-52c3-8497-782394c65c08/scratchpad/t5/ontology_v3_graph.json

======================================================================
  ЭТАП 3.5: Нормализация дат в orders.csv
======================================================================
  Резервная копия: orders.csv.bak
  Форматы: {'%Y-%m-%d': 46, '%d.%m.%Y': 14}
  Конвертировано: 14 строк

======================================================================
  ЭТАП 4: Анализ остатков
======================================================================
  Ключи: inventory.sku_code, order_items.item_ref, порог остатка = 40
  Позиций с остатком < 40: 2

======================================================================
  ЭТАП 5: ОТЧЁТ
======================================================================

--- Редуктор Р-120 (арт. 14) ---
  Склад:            Основной склад
  Остаток:          21 шт.
  Всего заказано:   47 шт.
  Скорость расхода: 0.16 шт./день
  До исчерпания:    ~131.8 дней
  >>> РЕКОМЕНДАЦИЯ: Заявка на 63 шт.

--- Насс Н-200А (арт. 24) ---
  Склад:            Региональный склад
  Остаток:          35 шт.
  Всего заказано:   79 шт.
  Скорость расхода: 0.17 шт./день
  До исчерпания:    ~205.1 дней
  >>> РЕКОМЕНДАЦИЯ: Заявка на 105 шт.

  Ключ ответов: /tmp/claude-0/-home-user-mass-palantir/3e6767ad-17b6-52c3-8497-782394c65c08/scratchpad/t5/answer_key.json

======================================================================
  ЭТАП 6: СВЕРКА С КЛЮЧОМ ОТВЕТОВ
======================================================================

--- 6.1 Legacy-поля ---
  customers.f_17: ✓
  orders.ref_9: ✓
  inventory.sku_code: ✓
  order_items.item_ref: ✓

--- 6.2 Дубли клиентов ---
  Найдено: 4/4, ложных: 0, пропущено: 0
  Precision: 100%, Recall: 100%

--- 6.3 Похожие товары НЕ объединены ---
  ✓ похожие товары не объединены

--- 6.4 Мусорные столбцы ---
  status_old_v1: ✓ исключён
  flag_2: ✓ исключён

======================================================================
  ИТОГ: 8/8 проверок пройдено
======================================================================
```
