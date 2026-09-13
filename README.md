# Dagens Skollunch

En enkel webbapplikation som visar skollunchen.

## Uppdatera menyerna

Kör följande kommando från projektets rot:

```sh
python3 scripts/fetch-menus.py
```

## Automatisk uppdatering

GitHub Actions uppdaterar menyerna varje vardag klockan 05:30 svensk tid och committar bara `data/menus.json` när innehållet har ändrats. Workflowet kan även köras manuellt från fliken **Actions** på GitHub.
