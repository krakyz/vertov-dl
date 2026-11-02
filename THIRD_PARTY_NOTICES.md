# Third-party notices

Лицензия MPL-2.0 применяется к исходному коду vertov-dl, а не заменяет лицензии зависимостей и изображений. Исходники проекта поставляются вместе с локальным репозиторием. Изменения предоставленных SVG: размер/цвет и обёртка, исходные векторные контуры сохранены.

## Иконки

| Файлы в apps/web/public/assets | Автор / источник | Лицензия |
|---|---|---|
| library-zoom.svg, library-trash.svg, df516.svg | Arturo Wibawa, https://github.com/artcoholic/akar-icons | MIT, LICENSES/akar-icons-MIT.txt |
| library-download.svg, c1a68.svg | Ant Design, https://github.com/ant-design/ant-design-icons | MIT, LICENSES/ant-design-MIT.txt |
| media-type-video.svg, 06dc2.svg, 0c228.svg, 6a143.svg | Andrés Raxón, https://github.com/andrsrxn/icons | MIT, LICENSES/andrsrxn-MIT.txt |
| library.svg | IBM Carbon, https://github.com/carbon-design-system/carbon | Apache-2.0, LICENSES/carbon-Apache-2.0.txt |
| media-type-audio.svg | Automattic Gridicons, https://github.com/Automattic/gridicons | GPL-2.0-only, LICENSES/gridicons-GPL-2.0.txt; этот отдельный SVG сохраняет GPL-2.0-only |
| library-convert.svg | Streamline Flex, https://streamlinehq.com / https://github.com/webalys-hq/streamline-vectors | CC-BY-4.0, LICENSES/streamline-CC-BY-4.0.txt; https://creativecommons.org/licenses/by/4.0/ |
| f6367.svg | VMware Clarity, https://github.com/vmware-clarity/core | MIT, LICENSES/clarity-MIT.txt |

13d3e.svg, c201c.svg и 594c9.svg — простые элементы предоставленного пользовательского макета (индикаторы и очистка). Неиспользуемые демонстрационные PNG из макета не включены в подготовленный репозиторий.

## Программные зависимости

- yt-dlp: https://github.com/yt-dlp/yt-dlp — Unlicense (Python source); дистрибутивы с зависимостями могут иметь дополнительные условия.
- FFmpeg: https://ffmpeg.org/legal.html — сборка Debian содержит собственные лицензии и /usr/share/doc/ffmpeg/copyright; поддержка libmp3lame/H.264 определяется сборкой. Файл copyright и полный список пакетов остаются в образе.
- Deno: https://github.com/denoland/deno — MIT, лицензия в образе поставщика.
- FastAPI, Uvicorn, Pydantic, SQLAlchemy, Vite: лицензии соответствующих пакетов (обычно MIT). TypeScript — Apache-2.0. PyCryptodome — BSD/public-domain notices согласно пакету.
- Полный закреплённый Python-состав: requirements.lock. Node-состав: package-lock.json. Installed dependency license inventory: docs/dependency-licenses.json.

Лицензионные notices установленных Python/Node-пакетов сохраняются в их dist-info/package directories при сборке. Бинарные образы для публичной поставки требуют сохранения исходников/ссылок на исходники соответствующих компонентов согласно их лицензиям; локальная подготовка не означает публикацию образа.
