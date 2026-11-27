from dataclasses import dataclass

type SpecificationValue = str | int | float


@dataclass(frozen=True, slots=True)
class ProductPreset:
    edition: str
    purpose: str
    price_range: tuple[int, int]
    specifications: dict[str, SpecificationValue | tuple[SpecificationValue, ...]]


@dataclass(frozen=True, slots=True)
class CategoryTemplate:
    slug: str
    name: str
    parent_slug: str
    series: str
    setup: str
    presets: tuple[ProductPreset, ...]


ROOT_CATEGORIES = {
    "electronics": "Электроника",
    "home-appliances": "Бытовая техника",
}

BRAND_NAMES = (
    "Астролив",
    "Бронтавик",
    "Вельмарика",
    "Грантевир",
    "Доренваль",
    "Ермоланис",
    "Желтарий",
    "Зорнелис",
    "Ильверна",
    "Кельмавир",
    "Лантарев",
    "Мердовей",
    "Норделика",
    "Острелин",
    "Прайвенор",
    "Ровентай",
    "Сиверлун",
    "Тарновея",
    "Ульмавент",
    "Фернолир",
    "Хальверад",
    "Циренволь",
    "Эрмовиль",
    "Яровелис",
)

CATEGORIES = (
    CategoryTemplate(
        "laptops",
        "Ноутбуки",
        "electronics",
        "NB",
        "Подключите блок питания и завершите первоначальную настройку операционной системы.",
        (
            ProductPreset(
                "Лайт",
                "учёбы, документов и видеозвонков",
                (34_000, 55_000),
                {
                    "cpu": "Лира M4",
                    "gpu": "Лира i4",
                    "ram_gb": (8, 16),
                    "ssd_gb": (256, 512),
                    "display_size_in": 14,
                    "resolution_width_px": 1920,
                    "resolution_height_px": 1080,
                    "battery_capacity_mah": 4100,
                    "os": "Linux",
                    "weight_g": 1450,
                },
            ),
            ProductPreset(
                "Студия",
                "программирования и многозадачной работы",
                (59_000, 99_000),
                {
                    "cpu": "Лира M8",
                    "gpu": "Лира i8",
                    "ram_gb": (16, 32),
                    "ssd_gb": (512, 1024),
                    "display_size_in": 14,
                    "resolution_width_px": 1920,
                    "resolution_height_px": 1200,
                    "battery_capacity_mah": 5200,
                    "os": "Linux",
                    "weight_g": 1520,
                },
            ),
            ProductPreset(
                "Арена",
                "игр и обработки видео",
                (95_000, 165_000),
                {
                    "cpu": "Лира H12",
                    "gpu": "Орбита G8",
                    "vram_gb": 8,
                    "ram_gb": (16, 32),
                    "ssd_gb": (1024, 2048),
                    "display_size_in": 16,
                    "resolution_width_px": 2560,
                    "resolution_height_px": 1600,
                    "refresh_rate_hz": 165,
                    "battery_capacity_mah": 6900,
                    "os": "без ОС",
                    "weight_g": 2350,
                },
            ),
        ),
    ),
    CategoryTemplate(
        "smartphones",
        "Смартфоны",
        "electronics",
        "PH",
        "Вставьте SIM-карту, настройте Wi-Fi и проверьте обновления системы.",
        (
            ProductPreset(
                "Связь",
                "звонков, мессенджеров и навигации",
                (12_000, 24_000),
                {
                    "cpu": "Сфера S6",
                    "ram_gb": (4, 6),
                    "storage_gb": (64, 128),
                    "camera_mp": 50,
                    "battery_capacity_mah": (4700, 5000),
                    "display_size_in": 6.5,
                    "refresh_rate_hz": 90,
                    "os": "Android",
                    "weight_g": 195,
                },
            ),
            ProductPreset(
                "Фокус",
                "мобильной фотографии и записи видео",
                (39_000, 89_000),
                {
                    "cpu": "Сфера X8",
                    "ram_gb": (8, 12),
                    "storage_gb": (256, 512),
                    "camera_mp": 108,
                    "battery_capacity_mah": (4900, 5300),
                    "display_size_in": 6.7,
                    "refresh_rate_hz": 120,
                    "os": "Android",
                    "weight_g": 210,
                },
            ),
        ),
    ),
    CategoryTemplate(
        "tablets",
        "Планшеты",
        "electronics",
        "TB",
        "Подключитесь к Wi-Fi и выполните начальную настройку с учётной записью владельца.",
        (
            ProductPreset(
                "Читалка",
                "чтения, учёбы и просмотра видео",
                (15_000, 29_000),
                {
                    "cpu": "Сфера S6",
                    "ram_gb": (4, 6),
                    "storage_gb": (64, 128),
                    "display_size_in": 10.1,
                    "resolution_width_px": 1920,
                    "resolution_height_px": 1200,
                    "battery_capacity_mah": 7000,
                    "os": "Android",
                    "weight_g": 485,
                },
            ),
            ProductPreset(
                "Эскиз",
                "рисования, конспектов и многозадачной работы",
                (33_000, 68_000),
                {
                    "cpu": "Сфера X8",
                    "ram_gb": (8, 12),
                    "storage_gb": (128, 256),
                    "display_size_in": 12.4,
                    "resolution_width_px": 2560,
                    "resolution_height_px": 1600,
                    "battery_capacity_mah": 9800,
                    "os": "Android",
                    "weight_g": 610,
                },
            ),
        ),
    ),
    CategoryTemplate(
        "computers",
        "Компьютеры",
        "electronics",
        "PC",
        "Подключите монитор и периферию, затем проверьте выбор видеовхода на мониторе.",
        (
            ProductPreset(
                "Офис",
                "офисных программ и работы с браузером",
                (30_000, 52_000),
                {
                    "cpu": "Лира D6",
                    "gpu": "Лира i6",
                    "ram_gb": 16,
                    "ssd_gb": (256, 512),
                    "power_w": 350,
                    "os": "Linux",
                    "weight_g": 4800,
                },
            ),
            ProductPreset(
                "Арена",
                "современных игр и видеомонтажа",
                (91_000, 168_000),
                {
                    "cpu": "Лира D12",
                    "gpu": "Орбита G12",
                    "vram_gb": 12,
                    "ram_gb": (32, 64),
                    "ssd_gb": (1024, 2048),
                    "power_w": 750,
                    "os": "без ОС",
                    "weight_g": 9200,
                },
            ),
        ),
    ),
    CategoryTemplate(
        "monitors",
        "Мониторы",
        "electronics",
        "MN",
        "Подключите совместимый видеокабель и выберите штатное разрешение в настройках системы.",
        (
            ProductPreset(
                "Текст",
                "работы с документами и таблицами",
                (10_000, 20_000),
                {
                    "display_size_in": 23.8,
                    "resolution_width_px": 1920,
                    "resolution_height_px": 1080,
                    "refresh_rate_hz": (75, 100),
                    "panel": "IPS",
                    "weight_g": 3100,
                },
            ),
            ProductPreset(
                "Движение",
                "динамичных игр и работы с графикой",
                (23_000, 46_000),
                {
                    "display_size_in": 27,
                    "resolution_width_px": 2560,
                    "resolution_height_px": 1440,
                    "refresh_rate_hz": (144, 165, 180),
                    "panel": "IPS",
                    "weight_g": 4650,
                },
            ),
        ),
    ),
    CategoryTemplate(
        "televisions",
        "Телевизоры",
        "electronics",
        "TV",
        "Установите телевизор на устойчивую опору и выполните настройку источника сигнала.",
        (
            ProductPreset(
                "Комната",
                "просмотра эфира и видео в небольшой комнате",
                (19_000, 32_000),
                {
                    "display_size_in": (32, 40),
                    "resolution_width_px": 1920,
                    "resolution_height_px": 1080,
                    "refresh_rate_hz": 60,
                    "panel": "LED",
                    "power_w": 65,
                },
            ),
            ProductPreset(
                "Кино",
                "фильмов и потокового видео в гостиной",
                (38_000, 85_000),
                {
                    "display_size_in": (50, 55, 65),
                    "resolution_width_px": 3840,
                    "resolution_height_px": 2160,
                    "refresh_rate_hz": 60,
                    "panel": "QLED",
                    "power_w": 135,
                },
            ),
        ),
    ),
    CategoryTemplate(
        "headphones",
        "Наушники",
        "electronics",
        "AU",
        "Проверьте способ подключения и настройте комфортный уровень громкости.",
        (
            ProductPreset(
                "Линия",
                "видеозвонков и прослушивания музыки за столом",
                (1700, 5900),
                {
                    "connection": "3,5 мм",
                    "form_factor": "накладные",
                    "weight_g": (150, 170),
                },
            ),
            ProductPreset(
                "Тишина",
                "поездок и работы в шумных помещениях",
                (7400, 21_000),
                {
                    "connection": "Bluetooth",
                    "form_factor": "полноразмерные",
                    "noise_cancellation": "активное",
                    "battery_capacity_mah": (540, 660),
                    "weight_g": 265,
                },
            ),
        ),
    ),
    CategoryTemplate(
        "gaming-components",
        "Игровые комплектующие",
        "electronics",
        "GC",
        "Перед установкой проверьте интерфейс, размеры корпуса и требования к питанию.",
        (
            ProductPreset(
                "Поток",
                "расширения хранилища для игр",
                (4600, 13_500),
                {
                    "component_type": "SSD",
                    "interface": "M.2 NVMe PCIe 4.0",
                    "ssd_gb": (1024, 2048),
                    "power_w": 7,
                    "weight_g": 9,
                },
            ),
            ProductPreset(
                "Кадр",
                "сборки игрового компьютера с дискретной графикой",
                (28_000, 78_000),
                {
                    "component_type": "видеокарта",
                    "interface": "PCIe 4.0 x16",
                    "gpu": "Орбита G12",
                    "vram_gb": 12,
                    "power_w": 210,
                    "weight_g": 825,
                },
            ),
        ),
    ),
    CategoryTemplate(
        "refrigerators",
        "Холодильники",
        "home-appliances",
        "RF",
        "Оставьте зазоры для вентиляции и проверьте требования к первому включению в инструкции.",
        (
            ProductPreset(
                "Компакт",
                "небольшой кухни и хранения ежедневного запаса продуктов",
                (22_000, 37_000),
                {
                    "volume_l": (160, 185),
                    "freezer_volume_l": 38,
                    "defrost_type": "капельная",
                    "weight_g": 43000,
                },
            ),
            ProductPreset(
                "Семья",
                "хранения продуктов и заморозки на несколько дней",
                (42_000, 83_000),
                {
                    "volume_l": (295, 345, 380),
                    "freezer_volume_l": 96,
                    "defrost_type": "No Frost",
                    "weight_g": 68000,
                },
            ),
        ),
    ),
    CategoryTemplate(
        "washing-machines",
        "Стиральные машины",
        "home-appliances",
        "WM",
        "Перед первым циклом снимите транспортировочные крепления согласно руководству.",
        (
            ProductPreset(
                "Узкая",
                "повседневной стирки при ограниченном месте для установки",
                (23_000, 38_000),
                {
                    "load_capacity_kg": (5, 6),
                    "spin_speed_rpm": 1000,
                    "depth_mm": 425,
                    "weight_g": 54500,
                },
            ),
            ProductPreset(
                "Семья",
                "стирки больших загрузок и постельного белья",
                (38_000, 64_000),
                {
                    "load_capacity_kg": (8, 9),
                    "spin_speed_rpm": (1200, 1400),
                    "depth_mm": 590,
                    "weight_g": 66800,
                },
            ),
        ),
    ),
    CategoryTemplate(
        "small-appliances",
        "Мелкая бытовая техника",
        "home-appliances",
        "SA",
        "Проверьте комплектность и ознакомьтесь с уходом за съёмными деталями до первого запуска.",
        (
            ProductPreset(
                "Чай",
                "быстрого кипячения воды",
                (1700, 5200),
                {
                    "appliance_type": "электрочайник",
                    "volume_l": (1.5, 1.7),
                    "power_w": (1800, 2000),
                    "weight_g": 1040,
                },
            ),
            ProductPreset(
                "Микс",
                "приготовления смузи и супов-пюре",
                (3800, 12_000),
                {
                    "appliance_type": "стационарный блендер",
                    "volume_l": (1.2, 1.5),
                    "power_w": (650, 850),
                    "weight_g": 2780,
                },
            ),
        ),
    ),
)
