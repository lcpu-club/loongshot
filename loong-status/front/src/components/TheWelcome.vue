<template>
  <header>
    <h1>Arch Linux for Loong64</h1>
  </header>
  <section>
    <h2>Introduction</h2>
    <p>This a port of <a href="https://archlinux.org/">Arch Linux</a> for <a href="https://www.loongson.cn/EN">Loong64</a> architecture.</p>
  </section>
  <section>
    <h2>Resources</h2>
    <ul>
      <li><router-link to="/status">Package Status</router-link></li>
      <li><router-link to="/stat">Package Statistics</router-link></li>
      <li><a href="https://github.com/lcpu-club/loongarch-packages">Patches collection</a></li>
      <li><a href="https://github.com/lcpu-club/loongshot">Git repository for infrastructure</a></li>
      <li>Package repos: <a href="https://mirrors.pku.edu.cn/loongarch-lcpu/archlinux/">https://mirrors.pku.edu.cn/loongarch-lcpu/archlinux/</a></li>
    </ul>
  </section>

  <section>
    <h2>Contributing</h2>
    <p>If you want to contribute to this project, you can help us improve our <a href="https://github.com/lcpu-club/loongshot">infrastructure</a>, write documentation, or provide <a href="https://github.com/lcpu-club/loongarch-packages">patches</a> for packages that <a href="/status?search=:fail">fail to build</a>.</p>
  </section>
</template>
