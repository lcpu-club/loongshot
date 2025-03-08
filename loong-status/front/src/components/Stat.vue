<template>
  <div class="table-container">
    <h1>Package Statistics</h1>
    <table class="table is-hoverable">
      <thead>
        <tr>
          <th rowspan="2">Arch</th>
          <th colspan="3">[core]</th>
          <th colspan="3">[extra]</th>
        </tr>
        <tr>
          <th>Up-to-date (Ratio%)</th>
          <th>Outdated</th>
          <th>Missing</th>
          <th>Up-to-date (Ratio%)</th>
          <th>Outdated</th>
          <th>Missing</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>x86_64</td>
          <td>{{ data.core_total }}</td>
          <td>0</td>
          <td>0</td>
          <td>{{ data.extra_total }}</td>
          <td>0</td>
          <td>0</td>
        </tr>
        <tr>
          <td>loong64</td>
          <td class="green-text">{{ formatCount(data.core_match, data.core_total) }}</td>
          <td class="orange-text">{{ data.core_mismatch }}</td>
          <td class="red-text">{{ data.core_total - data.core_mismatch - data.core_match }}</td>
          <td class="green-text">{{ formatCount(data.extra_match, data.extra_total) }}</td>
          <td class="orange-text">{{ data.extra_mismatch }}</td>
          <td class="red-text">{{ data.extra_total - data.extra_mismatch - data.extra_match }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue';
import axios from 'axios';

export default {
  setup() {
    const data = ref({
      core_total: 0,
      core_match: 0,
      core_mismatch: 0,
      extra_total: 0,
      extra_match: 0,
      extra_mismatch: 0,
    });

    // Function to format counts with a percentage
    const formatCount = (count, total) => {
      if (total === 0) return `${count} (0%)`;
      const percentage = ((count / total) * 100).toFixed(2);
      return `${count} (${percentage}%)`;
    };

    // Fetch data on mount
    onMounted(async () => {
      try {
        const response = await axios.get('/api/packages/stat');
        data.value = response.data;
      } catch (error) {
        console.error("Error fetching data:", error);
      }
    });

    return {
      data,
      formatCount,
    };
  },
};
</script>

<style scoped>
/* Table Styling */
table {
  border-collapse: collapse; /* Ensures no extra spacing */
  border-left: none;
  border-right: none;
}

th {
  font-weight: bold;
  border-bottom: 2px solid #ddd;
  padding: 8px;
  text-align: center;
}

td {
  border-bottom: 1px solid #ddd;
  padding: 8px;
  text-align: center;
}

tbody tr:hover {
  background: var(--color-background-mute);
}

/* Color Classes */
.orange-text {
  color: orange;
}
.red-text {
  color: red;
}
.green-text {
  color: green;
}
</style>

