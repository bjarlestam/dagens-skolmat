# Dagens Skollunch

En enkel webbapplikation som visar skollunchen för Kunskapsskolan Täby och Olympiaskolan.

Menyerna sparas i `data/menus.json` så att webbsidan inte behöver anropa externa tjänster från besökarens webbläsare.

## Uppdatera menyerna

Kör följande kommando från projektets rot:

```sh
python3 scripts/fetch-menus.py
```

Kunskapsskolan Täby publicerar sin officiella meny som bilder i ett Google-dokument. Därför kräver uppdateraren även `tesseract` för texttolkning. Olympias källa hämtas från Mashie.

## Automatisk uppdatering

GitHub Actions uppdaterar menyerna varje vardag klockan 06:15 svensk tid och committar bara `data/menus.json` när innehållet har ändrats. Workflowet kan även köras manuellt från fliken **Actions** på GitHub.
