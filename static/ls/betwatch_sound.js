// Счётчик для отслеживания новых сигналов
let previousSignalCount = 0;

// Функция воспроизведения звука
function playAlertSound() {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    
    // Двойной beep
    oscillator.frequency.value = 800;
    oscillator.type = 'sine';
    
    gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.2);
    
    oscillator.start();
    oscillator.stop(audioContext.currentTime + 0.2);
    
    // Второй beep через 250ms
    setTimeout(() => {
        const osc2 = audioContext.createOscillator();
        const gain2 = audioContext.createGain();
        osc2.connect(gain2);
        gain2.connect(audioContext.destination);
        osc2.frequency.value = 800;
        osc2.type = 'sine';
        gain2.gain.setValueAtTime(0.3, audioContext.currentTime);
        gain2.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.2);
        osc2.start();
        osc2.stop(audioContext.currentTime + 0.2);
    }, 250);
}

// Проверка новых сигналов при обновлении
function checkForNewSignals(currentCount) {
    if (currentCount > previousSignalCount && previousSignalCount > 0) {
        const newSignals = currentCount - previousSignalCount;
        
        // 🔊 Звук
        playAlertSound();
        
        // 🔔 Browser notification
        if (Notification.permission === "granted") {
            new Notification("🚨 Новый сигнал Betwatch!", {
                body: `Обнаружено ${newSignals} новых аномалий`,
                icon: '/static/favicon.ico'
            });
        }
        
        // Мигание заголовка
        flashTitle(newSignals);
    }
    
    previousSignalCount = currentCount;
}

// Мигание заголовка вкладки
function flashTitle(count) {
    const originalTitle = document.title;
    let flashCount = 0;
    
    const interval = setInterval(() => {
        document.title = flashCount % 2 === 0 
            ? `🔴 ${count} новых сигналов!` 
            : originalTitle;
        
        flashCount++;
        if (flashCount >= 10) {
            clearInterval(interval);
            document.title = originalTitle;
        }
    }, 500);
}

// Запрос разрешения на уведомления
document.addEventListener('DOMContentLoaded', () => {
    if (Notification.permission === "default") {
        Notification.requestPermission();
    }
});

// Экспортируем для использования
window.checkForNewSignals = checkForNewSignals;
