// frontend/src/components/OddsTable.jsx
import React, { useEffect, useState } from 'react';

export const OddsTable = ({ sport }) => {
  const [odds, setOdds] = useState([]);

  useEffect(() => {
    // WebSocket подключение
    const ws = new WebSocket('ws://localhost:8000/ws/live-odds');
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setOdds(data.filter(item => item.sport === sport));
    };

    return () => ws.close();
  }, [sport]);

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full bg-white">
        <thead className="bg-gray-800 text-white">
          <tr>
            <th>Событие</th>
            <th>Букмекер</th>
            <th>1</th>
            <th>X</th>
            <th>2</th>
            <th>Время</th>
          </tr>
        </thead>
        <tbody>
          {odds.map(row => (
            <tr key={row.id} className="border-b hover:bg-gray-50">
              <td>{row.event_name}</td>
              <td>{row.bookmaker}</td>
              <td className="font-bold">{row.odd_1}</td>
              <td>{row.odd_x}</td>
              <td>{row.odd_2}</td>
              <td>{new Date(row.created_at).toLocaleTimeString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
