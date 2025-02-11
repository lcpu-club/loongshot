<template>
  <div>
    <div align="left" style="margin: 20px">
      <input v-model="searchQuery" placeholder="Search..." />
      <button @click="onSearch">Search</button>
    </div>
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in data" :key="row.id">
            <td v-for="column in columns" :key="column">{{ row[column] }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div>
      <button @click="prevPage" :disabled="currentPage === 1">Previous</button>
      <span>Page {{ currentPage }} of {{ totalPages }}</span>
      <button @click="nextPage" :disabled="currentPage === totalPages">Next</button>
      <input v-model.number="goToPage" type="number" min="1" :max="totalPages" />
      <button @click="goToSpecificPage">Go</button>
    </div>
  </div>
</template>

<script>
import { ref, computed } from 'vue';

export default {
  props: {
    data: {
      type: Array,
      required: true,
    },
    columns: {
      type: Array,
      required: true,
    },
    total: {
      type: Number,
      required: true,
    },
    perPage: {
      type: Number,
      required: true,
    },
  },
  emits: ['page-change', 'search'],
  setup(props, { emit }) {
    const currentPage = ref(1);
    const searchQuery = ref('');
    const goToPage = ref(1);

    const totalPages = computed(() => {
      return Math.ceil(props.total / props.perPage);
    });

    const onSearch = () => {
      currentPage.value = 1; // 重置到第一页
      emit('search', searchQuery.value);
    };

    const nextPage = () => {
      if (currentPage.value < totalPages.value) {
        currentPage.value++;
        emit('page-change', { page: currentPage.value, search: searchQuery.value });
      }
    };

    const prevPage = () => {
      if (currentPage.value > 1) {
        currentPage.value--;
        emit('page-change', { page: currentPage.value, search: searchQuery.value });
      }
    };

    const goToSpecificPage = () => {
      if (goToPage.value >= 1 && goToPage.value <= totalPages.value) {
        currentPage.value = goToPage.value;
        emit('page-change', { page: currentPage.value, search: searchQuery.value });
      }
    };

    return {
      currentPage,
      searchQuery,
      goToPage,
      totalPages,
      onSearch,
      nextPage,
      prevPage,
      goToSpecificPage,
    };
  },
};
</script>

<style scoped>

.table-container {
  width: calc(100% - 40px);
  overflow-x: auto;
  margin: 20px;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th, td {
  border: 1px solid #ddd;
  padding: 8px;
  text-align: left;
}

td {
  white-space: nowrap;
  overflow: hidden;
  text-overflow:ellipsis;
}

th {
  background-color: #f4f4f4;
}

input {
  height: 30px;
}
</style>
