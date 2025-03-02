<template>
  <div>
    <div>
      <input type="number" v-model="taskid" />
      <button style="width: 100px;" @click="prevTask">Previous</button>
      <button style="width: 100px;" @click="nextTask">Next</button>
    </div>

    <table>
      <thead>
        <tr>
          <th>Package Base</th>
          <th>Repo</th>
          <th>Finish Time</th>
          <th>Build Result</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="task in tasks" :key="task.pkgbase">
          <td>{{ task.pkgbase }}</td>
          <td>{{ task.repo }}</td>
          <td>{{ task.build_time }}</td>
          <td>{{ task.build_result }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script>
import { useRoute } from 'vue-router';
import { ref, watch, onMounted } from "vue";

export default {
  setup() {
    const taskid = ref(0);
    const tasks = ref([]);
    const route = useRoute();

    // Fetch data from the backend API
    const fetchData = async () => {
      try {
        const response = await fetch(`/api/tasks/result?taskid=${taskid.value}`);
        if (!response.ok) throw new Error("Failed to fetch tasks");
        const data = await response.json();
        tasks.value = data.map((task) => ({
          ...task,
          build_time: convertToLocalTime(task.build_time),
          repo: lookupRepo(task.repo),
          build_result: lookupBuildResult(task.build_result), // Lookup for build result
        }));
      } catch (error) {
        console.error("Error fetching task data:", error);
      }
    };

    const lookupRepo = (repo) => {
      const repo_name = ['stable', 'testing', 'staging'];
      return repo_name[repo];
    }

    const convertToLocalTime = (utcTime) => {
      if (!utcTime) return '';
      const date = new Date(utcTime); // Create a Date object from the UTC string
      return date.toLocaleString(); // Convert to local string format (local time zone)
    };

    // Lookup for the build result values
    const lookupBuildResult = (result) => {
      const fail_reason = ['Fail to apply patch',
          'Fail before build',
          'Fail to download source',
          'Fail to pass the validity check',
          'Fail to pass PGP check',
          'Could not resolve all dependencies',
          'Fail in prepare',
          'Fail in build',
          'Fail in check',
          'Fail in package',
          'Old config.guess'];
      if (! result) return "Waiting";
      if (!(result & (1 << 15))) return "Done"
      return fail_reason[(result >> 16) - 1];
    };

    // Update the taskid and fetch data when it's changed
    const nextTask = () => {
      taskid.value += 1;
    };

    const prevTask = () => {
      taskid.value -= 1;
    };

    // Watch for changes to taskid and refetch data
    watch(taskid, fetchData);

    // Fetch data when component is mounted
    onMounted(() => {
      if (route.query.taskid) {
        taskid.value = route.query.taskid;
      }
      fetchData();
    });

    return {
      taskid,
      tasks,
      nextTask,
      prevTask,
    };
  },
};
</script>
<style scoped>
table {
  width: 100%;
  border-collapse: collapse;
}

th, td {
  border: 1px solid #ddd;
  white-space: pre-line;
  word-wrap: break-word;
  padding: 8px;
  text-align: left;
}

td {
  overflow: hidden;
  text-overflow:ellipsis;
}

th {
  color: #101010;
  background-color: #f4f4f4;
}

tr:hover {
  background-color: #f0f0f0;
  cursor: pointer;
}
</style>
