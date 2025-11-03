document.addEventListener("DOMContentLoaded", function () {
  fetch("/api/matches")
    .then((response) => response.json())
    .then((data) => {
      const tableBody = document.getElementById("match-table-body");
      tableBody.innerHTML = "";

      data.forEach((match) => {
        const row = document.createElement("tr");

        row.innerHTML = `
          <td>${match.league}</td>
          <td>${match.match_name}</td>
          <td>${match.odds1}</td>
          <td>${match.odds2}</td>
        `;

        tableBody.appendChild(row);
      });
    })
    .catch((error) => {
      console.error("Ошибка загрузки данных:", error);
    });
});
