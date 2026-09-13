document.addEventListener('DOMContentLoaded', () => {
    fetchMenu('kunskapsskolan-taby');
    fetchMenu('olympia');
});

async function fetchMenu(schoolKey) {
    const statusEl = document.getElementById(`${schoolKey}-status`);
    const dishEl = document.getElementById(`${schoolKey}-dish`);
    const labelEl = document.getElementById(`${schoolKey}-label`);
    const upcomingListEl = document.getElementById(`${schoolKey}-upcoming`);

    try {
        const response = await fetch('data/menus.json');

        if (!response.ok) throw new Error('Nätverksfel');

        const menus = await response.json();
        const schoolMenu = menus[schoolKey];

        if (!schoolMenu?.days?.length) {
            throw new Error('Ingen meny hittades');
        }

        processMenuData(schoolMenu.days, labelEl, dishEl, statusEl, upcomingListEl);

    } catch (error) {
        console.error(error);
        statusEl.textContent = 'Fel vid hämtning';
        statusEl.style.color = '#ff3b30';
        dishEl.textContent = 'Kunde inte ladda menyn.';
    }
}

function processMenuData(days, labelEl, dishEl, statusEl, upcomingListEl) {
    const now = new Date();
    const currentHour = now.getHours();
    const showNextDay = currentHour >= 18;

    const today = startOfDay(now);
    let targetDate = new Date(today);
    let labelText = 'Dagens Lunch';

    if (showNextDay) {
        targetDate.setDate(today.getDate() + 1);
        labelText = 'I Morgon';
    }

    const dayEntries = days
        .map((entry) => ({
            date: parseLocalDate(entry.date),
            dish: entry.dish,
        }))
        .filter((entry) => entry.date && entry.dish)
        .sort((a, b) => a.date - b.date);

    if (dayEntries.length === 0) {
        dishEl.textContent = 'Ingen meny hittades online.';
        return;
    }

    let mainEntry = dayEntries.find((entry) => isSameDay(entry.date, targetDate));

    if (!mainEntry && showNextDay) {
        mainEntry = dayEntries.find((entry) => entry.date > today);
        if (mainEntry) labelText = 'Nästa Lunch';
    } else if (!mainEntry && !showNextDay) {
        mainEntry = dayEntries.find((entry) => entry.date >= today);
        if (mainEntry) labelText = 'Nästa Lunch';
    }

    if (!mainEntry) {
        mainEntry = dayEntries[0];
        labelText = 'Aktuell Meny';
    }

    labelEl.textContent = `${labelText} - ${formatSwedishDate(mainEntry.date)}`;
    dishEl.textContent = mainEntry.dish;
    statusEl.style.display = 'none';

    const mainIndex = dayEntries.indexOf(mainEntry);
    const upcomingEntries = dayEntries.slice(mainIndex + 1, mainIndex + 4);

    upcomingListEl.innerHTML = '';

    if (upcomingEntries.length === 0) {
        const li = document.createElement('li');
        li.textContent = 'Inga fler menyer laddade.';
        upcomingListEl.appendChild(li);
        return;
    }

    upcomingEntries.forEach((entry) => {
        const li = document.createElement('li');
        li.className = 'upcoming-item';
        li.innerHTML = `
            <span class="upcoming-date">${formatSwedishDate(entry.date)}</span>
            <span class="upcoming-dish">${entry.dish}</span>
        `;
        upcomingListEl.appendChild(li);
    });
}

function parseLocalDate(dateString) {
    const [year, month, day] = dateString.split('-').map(Number);
    if (!year || !month || !day) return null;
    return new Date(year, month - 1, day);
}

function startOfDay(date) {
    const copy = new Date(date);
    copy.setHours(0, 0, 0, 0);
    return copy;
}

function isSameDay(left, right) {
    return left.getFullYear() === right.getFullYear()
        && left.getMonth() === right.getMonth()
        && left.getDate() === right.getDate();
}

function formatSwedishDate(date) {
    const weekday = date.toLocaleDateString('sv-SE', { weekday: 'long' });
    const dayMonth = date.toLocaleDateString('sv-SE', { day: 'numeric', month: 'short' }).replace('.', '');
    return `${weekday}, ${dayMonth}`;
}

function toggleDetails(schoolKey) {
    const cardEl = document.getElementById(schoolKey);
    cardEl.classList.toggle('expanded');
}
