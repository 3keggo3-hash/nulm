# Optional Dependencies

Claude Bridge core kurulumu opsiyonel paketler olmadan calisabilmelidir.
Opsiyonel ozellikler runtime'da graceful fallback yapmali ve `mypy src`
core ortamda import hatasi uretmemelidir.

## Pattern

Opsiyonel importlarda tercih edilen desen:

1. Public olmayan typed degiskeni once `None` olarak tanimla.
2. Import edilen sembolu farkli bir alias ile al.
3. Basarili importtan sonra typed degiskene ata.
4. `# type: ignore[import-not-found]` yorumunu yalniz opsiyonel import satirinda
   kullan.
5. Runtime kullanimindan once availability flag veya `None` kontrolu yap.

Ornek:

```python
from typing import Any, Callable

_OptionalFunc = Callable[[bytes], Any]
_optional_func: _OptionalFunc | None = None
_OPTIONAL_AVAILABLE = False

try:
    from optional_package import func as _imported_optional_func  # type: ignore[import-not-found]

    _optional_func = _imported_optional_func
    _OPTIONAL_AVAILABLE = True
except ImportError:
    pass
```

## Doctor Kontrolleri

`claude-bridge doctor` su opsiyonel alanlari gorunur kilar:

- dev toolchain: `pytest`, `pytest-asyncio`, `ruff`, `black`, `mypy`
- smart extra: `tiktoken`, `charset_normalizer`
- indexing extra: `tree_sitter_language_pack`

Eksik opsiyonel paketler core kullanim icin hata sayilmaz; doctor ciktisi ilgili
extra kurulum komutunu gostermelidir.
