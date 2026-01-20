<template>
  <div>
    <div>
      <!-- Use a local display ID or the one from route -->
      <input
        type="number"
        v-model.number="displayTaskId"
        @keyup.enter="goToTask"
      />
      <button style="width: 100px" @click="prevTask">Previous</button>
      <button style="width: 100px" @click="nextTask">Next</button>
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
          <td v-html="task.build_result"></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
<script>
import { useRoute, useRouter } from "vue-router";
import { ref, watch, onMounted } from "vue";

export default {
  setup() {
    const route = useRoute();
    const router = useRouter();
    const tasks = ref([]);
    const displayTaskId = ref(0);

    const fetchData = async () => {
      // Get taskid from URL params (e.g., /task/123)
      const tid = route.params.taskid || 0;

      try {
        const response = await fetch(`/api/tasks/result?taskid=${tid}`);
        if (!response.ok) throw new Error("Failed to fetch");

        const data = await response.json();

        // Update local state with data from backend
        tasks.value = data.tasks.map((task) => ({
          ...task,
          build_time: convertToLocalTime(task.build_time),
          repo: lookupRepo(task.repo),
          build_result: lookupBuildResult(task.build_result, task.pkgbase),
        }));

        // Sync the input box and URL with the ACTUAL ID returned by the server
        displayTaskId.value = data.taskid;

        // If the URL was empty (/task) or different, update it without reloading
        if (route.params.taskid !== String(data.taskid)) {
          router.replace({ params: { taskid: data.taskid } });
        }
      } catch (error) {
        console.error("Error fetching task data:", error);
      }
    };

    const nextTask = () => {
      const nextId = parseInt(displayTaskId.value) + 1;
      router.push(`/task/${nextId}`);
    };

    const prevTask = () => {
      const prevId = parseInt(displayTaskId.value) - 1;
      router.push(`/task/${prevId}`);
    };

    const goToTask = () => {
      router.push(`/task/${displayTaskId.value}`);
    };

    // Watch for URL parameter changes
    watch(
      () => route.params.taskid,
      () => {
        fetchData();
      },
    );

    onMounted(() => {
      fetchData();
    });

    const lookupRepo = (repo) =>
      ["stable", "testing", "staging"][repo] || "unknown";

    const convertToLocalTime = (utcTime) => {
      if (!utcTime) return "";
      return new Date(utcTime).toLocaleString();
    };

    const lookupBuildResult = (info, base) => {
      const fail_reason = [
        "Unknown error",
        "Failed to apply patch",
        "Failed before build",
        "Failed to download source",
        "Failed to pass the validity check",
        "Failed to pass the PGP check",
        "Could not resolve all dependencies",
        "Failed in preparation",
        "Failed in build",
        "Failed in check",
        "Failed in packaging",
        "Outdated config.guess",
      ];
      if (!info) return "Waiting";
      if (info === "nolog") return "No Log";
      if (info === "building") return "Building";

      let value = info;
      if (info === "done") value = "Done";
      else if (info.startsWith("failed:")) {
        const failIndex = parseInt(info.split(":")[1], 10);
        value = fail_reason[failIndex] || "Unknown Failure";
      }
      return `<a href="/log.html?url=/buildlogs/${base}/all.log">${value}</a>`;
    };

    return {
      displayTaskId,
      tasks,
      nextTask,
      prevTask,
      goToTask,
    };
  },
};
</script>
<style scoped>
table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  border: 1px solid #ddd;
  white-space: pre-line;
  word-wrap: break-word;
  padding: 8px;
  text-align: left;
}

td {
  overflow: hidden;
  text-overflow: ellipsis;
}

th {
  color: #101010;
  background-color: #f4f4f4;
}

tr:hover {
  background: var(--color-background-mute);
}
</style>
