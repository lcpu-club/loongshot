document.addEventListener("DOMContentLoaded", function() {
    var table = document.getElementById("pkgTable");
    var rows = table.getElementsByTagName("tr");

    for (var i = 0; i < rows.length; i++) {
        var cells = rows[i].getElementsByTagName("td");

        if (cells.length > 4) {
            var loongCell = cells[1].innerText;
            var x86Cell = cells[2].innerText;
            var statusCell = cells[4];

            if (loongCell === x86Cell) {
                statusCell.classList.add("highlight-green");
            }
            if (statusCell === "failed") {
                statusCell.classList.add("highlight-red");
            }
        }
    }
});

