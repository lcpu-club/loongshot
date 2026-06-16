<template>
  <div>
    <!-- All query controls in one row -->
    <div class="query-bar">
      <input
        type="number"
        v-model.number="displayTaskId"
        @keyup.enter="goToTask"
        placeholder="Task ID"
        class="task-id-input"
      />
      <button class="btn" @click="prevTask">&lt; Prev</button>
      <button class="btn" @click="nextTask">Next &gt;</button>
      <span class="query-label">By Date:</span>
      <input type="date" v-model="selectedDate" class="native-date-picker" />
      <button class="btn" @click="searchByDate">Search</button>
    </div>

    <!-- Summary view: multiple taskids matched -->
    <div v-if="isSummary" class="summary-section">
      <h3>{{ summaries.length }} Task(s) on this date</h3>
      <table>
        <thead>
          <tr>
            <th>Task ID</th>
            <th>First Pkgbase</th>
            <th>Records</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in summaries" :key="item.taskid">
            <td>{{ item.taskid }}</td>
            <td>{{ item.pkgbase }}</td>
            <td>{{ item.count }}</td>
            <td>
              <button @click="goToTask(item.taskid)" class="view-link">
                View
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Full task list view -->
    <table v-else>
      <thead>
        <tr>
          <th>Task No</th>
          <th>Package Base</th>
          <th>Repo</th>
          <th>Finish Time</th>
          <th>Build Result</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="task in tasks" :key="task.pkgbase + '-' + task.taskno">
          <td>{{ task.taskno }}</td>
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
  // ElementPlus is globally registered in main.js
  setup() {
    const route = useRoute();
    const router = useRouter();
    const tasks = ref([]);
    const summaries = ref([]);
    const isSummary = ref(false);
    const displayTaskId = ref(0);
    const selectedDate = ref("");

    const resetState = () => {
      tasks.value = [];
      summaries.value = [];
      isSummary.value = false;
    };

    const mapTaskData = (tasks) =>
      tasks.map((task) => ({
        ...task,
        build_time: convertToLocalTime(task.build_time),
        repo: lookupRepo(task.repo),
        build_result: lookupBuildResult(task.build_result, task.pkgbase),
      }));

    const fetchData = async () => {
      const tid = route.params.taskid || 0;

      try {
        resetState();
        const response = await fetch(`/api/tasks/result?taskid=${tid}`);
        if (!response.ok) throw new Error("Failed to fetch");

        const data = await response.json();

        tasks.value = mapTaskData(data.tasks);

        if (data.taskid !== undefined) {
          displayTaskId.value = data.taskid;
        }

        if (route.params.taskid !== String(data.taskid)) {
          router.replace({ params: { taskid: data.taskid } });
        }
      } catch (error) {
        console.error("Error fetching task data:", error);
      }
    };

    const fetchByDate = async (dateStr) => {
      try {
        resetState();
        const response = await fetch(
          `/api/tasks/by_build_time?build_time=${encodeURIComponent(dateStr)}`,
        );
        if (!response.ok) throw new Error("Failed to fetch");

        const data = await response.json();

        if (Array.isArray(data)) {
          if (data.length === 0) {
            return;
          }
          summaries.value = data;
          isSummary.value = true;
          tasks.value = [];
        } else if (data.tasks) {
          tasks.value = mapTaskData(data.tasks);
          if (data.taskid !== undefined) {
            displayTaskId.value = data.taskid;
          }
        }
      } catch (error) {
        console.error("Error fetching by build_time:", error);
      }
    };

    const searchByDate = () => {
      if (!selectedDate.value) return;
      fetchByDate(selectedDate.value);
    };

    const nextTask = () => {
      router.push(`/task/${Number(displayTaskId.value) + 1}`);
    };

    const prevTask = () => {
      router.push(`/task/${Number(displayTaskId.value) - 1}`);
    };

    const goToTask = (taskId) => {
      const id = taskId !== undefined ? taskId : Number(displayTaskId.value);
      // Use router.resolve to generate the URL and force navigation
      const route = router.resolve({ path: `/task/${id}` });
      window.location.href = route.href;
    };

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
      summaries,
      isSummary,
      selectedDate,
      nextTask,
      prevTask,
      goToTask,
      searchByDate,
    };
  },
};
</script>
<style scoped>
.query-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: nowrap;
}

.task-id-input {
  width: 80px;
  padding: 2px 6px;
  font-size: 0.85rem;
}

.btn {
  width: 65px;
  font-size: 0.8rem;
  padding: 2px 4px;
}

.query-label {
  font-size: 0.85rem;
  color: var(--color-text);
  white-space: nowrap;
}

.native-date-picker {
  padding: 2px 6px;
  font-size: 0.85rem;
  width: 155px;
  cursor: pointer;
}

.summary-section {
  margin-bottom: 12px;
}

.summary-section h3 {
  color: #9b2d35;
  margin-bottom: 6px;
  font-size: 1rem;
}

.view-link {
  color: #9b2d35;
  text-decoration: none;
  font-weight: bold;
  font-size: 0.85rem;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  display: inline;
}

.view-link:hover {
  text-decoration: underline;
}

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
