const SCHOOL_URLS = {
    karby: 'https://mpi.mashie.com/public/app/Vallentuna%20kommun/0957e55a',
    olympia: 'https://mpi.mashie.com/public/app/Vallentuna%20kommun/b22e74ea'
};

// api.codetabs.com is more reliable for this specific source than allorigins
const CORS_PROXY = 'https://api.codetabs.com/v1/proxy/?quest=';

document.addEventListener('DOMContentLoaded', () => {
    fetchMenu('karby');
    fetchMenu('olympia');
});

async function fetchMenu(schoolKey) {
    const statusEl = document.getElementById(`${schoolKey}-status`);
    const dishEl = document.getElementById(`${schoolKey}-dish`);
    const labelEl = document.getElementById(`${schoolKey}-label`);
    const upcomingListEl = document.getElementById(`${schoolKey}-upcoming`);

    try {
        const targetUrl = SCHOOL_URLS[schoolKey];
        const response = await fetch(`${CORS_PROXY}${targetUrl}`);

        if (!response.ok) throw new Error('Nätverksfel');

        const data = await response.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(data, 'text/html');

        processMenuData(doc, schoolKey, labelEl, dishEl, statusEl, upcomingListEl);

    } catch (error) {
        console.error(error);
        statusEl.textContent = 'Fel vid hämtning';
        statusEl.style.color = '#ff3b30';
        dishEl.textContent = 'Kunde inte ladda menyn.';
    }
}

function processMenuData(doc, schoolKey, labelEl, dishEl, statusEl, upcomingListEl) {
    const now = new Date();
    const currentHour = now.getHours();

    // Logic: 
    // < 18:00 = Show today's lunch
    // >= 18:00 = Show tomorrow's lunch

    const showNextDay = currentHour >= 18;

    // Select all daily panels
    const panels = Array.from(doc.querySelectorAll('.panel-group .panel'));

    if (panels.length === 0) {
        dishEl.textContent = 'Ingen meny hittades online.';
        return;
    }

    // Helper to parse date from panel header text "Ons 12 feb" or "12 feb"
    const getPanelDate = (panel) => {
        const headerText = panel.querySelector('.panel-heading')?.textContent.trim().toLowerCase();
        if (!headerText) return null;

        // Match day and month
        const match = headerText.match(/(\d+)\s+([a-zåäö]{3})/);
        if (!match) return null;

        const day = parseInt(match[1], 10);
        const monthStr = match[2];
        const months = ['jan', 'feb', 'mar', 'apr', 'maj', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec'];
        const monthIndex = months.indexOf(monthStr);

        if (monthIndex === -1) return null;

        const year = now.getFullYear(); // Assume current year
        const date = new Date(year, monthIndex, day);

        // Handle year wrap-around (e.g. looking at Jan in Dec)
        if (monthIndex === 0 && now.getMonth() === 11) {
            date.setFullYear(year + 1);
        }

        return date;
    };

    // Find the panel for "Today"
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    let targetDate = new Date(today);
    let labelText = 'Dagens Lunch';

    if (showNextDay) {
        // If it's after 18:00, we prefer to show tomorrow.
        // We need to find the panel that matches tomorrow.
        targetDate.setDate(today.getDate() + 1);
        labelText = 'I Morgon';
    }

    // Find the panel that matches targetDate
    let mainPanel = panels.find(p => {
        const d = getPanelDate(p);
        return d && d.getDate() === targetDate.getDate() && d.getMonth() === targetDate.getMonth();
    });

    // Fallback logic:
    // If showNextDay is true but we can't find tomorrow (e.g. tomorrow is weekend),
    // we should show the next AVAILABLE day.
    if (!mainPanel && showNextDay) {
        // Find the first panel that is effectively "in the future" relative to today
        mainPanel = panels.find(p => {
            const d = getPanelDate(p);
            return d && d > today;
        });
        if (mainPanel) {
            // Update label to reflect it's not strictly "tomorrow" but the next one
            // Or just keep "Kommande" / "Nästa Skoldag"
            labelText = 'Nästa Lunch';
        }
    } else if (!mainPanel && !showNextDay) {
        // If we want today but can't find it (maybe weekend or passed?), show next available
        mainPanel = panels.find(p => {
            const d = getPanelDate(p);
            return d && d >= today;
        });
        if (mainPanel) labelText = 'Nästa Lunch';
    }

    // If still no panel (e.g. end of term), just default to first available
    if (!mainPanel && panels.length > 0) {
        mainPanel = panels[0];
        labelText = 'Aktuell Meny';
    }

    if (mainPanel) {
        // Extract Dish
        // First look for the main dish container
        // Sometimes there are multiple options (Lunch 1, Lunch 2). We usually pick the first one.

        const menuItems = mainPanel.querySelectorAll('.list-group-item-menu');
        let dishName = '';

        if (menuItems.length > 0) {
            // Find the item that looks like the main course.
            // Usually the first one.
            const firstItem = menuItems[0];
            const nameEl = firstItem.querySelector('.app-daymenu-name');
            if (nameEl) dishName = nameEl.textContent.trim();
        } else {
            // Fallback for weird layout
            dishName = mainPanel.querySelector('.app-daymenu-name')?.textContent.trim();
        }

        if (!dishName) dishName = 'Ingen matsedel';

        // Helper to format date: "onsdag, 12 feb"
        const formatSwedishDate = (date) => {
            const weekday = date.toLocaleDateString('sv-SE', { weekday: 'long' });
            const dayMonth = date.toLocaleDateString('sv-SE', { day: 'numeric', month: 'short' }).replace('.', '');
            return `${weekday}, ${dayMonth}`;
        };

        // Extract Date from Panel for Display
        const panelDate = getPanelDate(mainPanel);

        if (panelDate) {
            labelEl.textContent = `${labelText} - ${formatSwedishDate(panelDate)}`;
            // Lowercase the label labelText? User said "i morgon - fredag..."
            // But typical UI is Title Case. "I Morgon - fredag, 13 feb" looks good.
            // Let's stick to the prompt's lowercase style for the appended part.
        } else {
            labelEl.textContent = labelText;
        }

        dishEl.textContent = dishName;
        statusEl.textContent = 'Uppdaterad';

        // Populate Upcoming (Details View)
        // We list panels appearing AFTER the mainPanel in the customized list (but verify they are future)
        const mainIndex = panels.indexOf(mainPanel);

        // We just take the next few available panels
        const upcomingPanels = panels.slice(mainIndex + 1, mainIndex + 4); // Next 3

        upcomingListEl.innerHTML = ''; // clear

        if (upcomingPanels.length === 0) {
            const li = document.createElement('li');
            li.textContent = 'Inga fler menyer laddade.';
            upcomingListEl.appendChild(li);
        }

        upcomingPanels.forEach(p => {
            const pDate = getPanelDate(p);
            const dishStr = p.querySelector('.app-daymenu-name')?.textContent.trim();

            if (pDate && dishStr) {
                const dateStr = formatSwedishDate(pDate);
                const li = document.createElement('li');
                li.className = 'upcoming-item';
                li.innerHTML = `
                    <span class="upcoming-date">${dateStr}</span>
                    <span class="upcoming-dish">${dishStr}</span>
                `;
                upcomingListEl.appendChild(li);
            }
        });

    } else {
        dishEl.textContent = 'Kunde inte hitta nästa lunch.';
    }
}

function toggleDetails(schoolKey) {
    const cardEl = document.getElementById(schoolKey);
    cardEl.classList.toggle('expanded');

    // We don't strictly need to toggle 'hidden' on detailsEl anymore 
    // because CSS handles the visibility via max-height/opacity on .expanded
    // However, keeping accessible attributes is good practice.
    // Let's just rely on the CSS 'expanded' class for the visual toggle.
}
