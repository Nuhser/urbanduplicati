<template>
  <div class="ud-page">
    <div class="ud-page-header">
      <NcButton type="tertiary" @click="$router.push({ name: 'tasks' })">← {{ t('dupli', 'Back') }}</NcButton>
      <h2>{{ currentTask ? (currentTask.name || t('dupli', 'Scan') + ' #' + id) : t('dupli', 'Loading…') }}</h2>
      <span class="ud-header-meta" v-if="totals">
        {{ totals.groupstotal }} {{ t('dupli', 'groups') }} ·
        {{ totals.filestotal }} {{ t('dupli', 'files') }} ·
        {{ formatBytes(totals.filessize) }}
      </span>
    </div>

    <!-- Filter bar -->
    <div class="ud-filter-bar">
      <input
        v-model="filterPattern"
        type="text"
        class="ud-filter-input"
        :placeholder="t('dupli', 'Filter by filename glob, e.g. IMG* or *.jpg')"
        @keyup.enter="applyFilter"
      />
      <NcButton type="secondary" @click="applyFilter">{{ t('dupli', 'Apply') }}</NcButton>
      <NcButton v-if="filterPattern" type="tertiary" @click="clearFilter">✕ {{ t('dupli', 'Clear') }}</NcButton>
      <span v-if="activeFilter" class="ud-filter-active">
        🔍 {{ t('dupli', 'Showing groups with files matching') }}: <strong>{{ activeFilter }}</strong>
        · {{ t('dupli', 'Matching files marked for deletion') }}
      </span>
    </div>

    <!-- Bulk toolbar -->
    <div class="ud-bulk-toolbar" v-if="!groupsLoading && totals && Number(totals.groupstotal) > 0">
      <label class="ud-check-all">
        <input type="checkbox" :checked="allCurrentSelected" @change="toggleCurrentPage" />
        <span v-if="allGroupsSelected" class="ud-select-status ud-select-status--all">
          ✅ {{ t('dupli', 'All') }} {{ allSelectedIds.length }} {{ t('dupli', 'groups selected') }}
          <button class="ud-link-btn" @click="clearAllSelection">{{ t('dupli', 'Clear') }}</button>
        </span>
        <span v-else-if="selectedGroups.size > 0" class="ud-select-status">
          {{ selectedGroups.size }} {{ t('dupli', 'selected on this page') }} ·
          <button class="ud-link-btn" @click="selectAllPages">
            {{ t('dupli', 'Select all') }} {{ totals.groupstotal }} {{ t('dupli', 'groups') }}
          </button>
        </span>
        <span v-else>{{ t('dupli', 'Select all on this page') }}</span>
      </label>

      <div class="ud-bulk-actions" v-if="selectedGroups.size > 0 || allGroupsSelected">
        <span class="ud-savings-badge">
          🗑 ~{{ formatBytes(estimatedSavings) }} {{ t('dupli', 'freed') }}
          <span v-if="protectedSkipCount !== 0" class="ud-savings-protected">
            · {{ protectedSkipCount === -1 ? '🛡 ' + t('dupli', 'protected files kept') : protectedSkipCount + ' 🛡 ' + t('dupli', 'kept') }}
          </span>
        </span>
        <div v-if="rules && rules.length > 0" class="ud-keep-folder-row">
          <label class="ud-keep-folder-label">
            <input type="checkbox" v-model="deleteUnprotectedAndKeepOne" />
            {{ t('dupli', 'Also delete protected duplicates, keeping files from:') }}
          </label>
          <select v-if="deleteUnprotectedAndKeepOne" v-model="keepFromFolder" class="ud-keep-folder-select">
            <option value="">{{ t('dupli', '— select folder to keep —') }}</option>
            <option v-for="rule in rules" :key="rule.id" :value="rule.path">
              {{ rule.label || rule.path }}
            </option>
          </select>
        <div style="display:block; width:100%; margin-top:8px;" v-if="activeGroupIds.length > 0">
          <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
            <input type="checkbox" v-model="selectAllProtected" @change="onSelectAllProtected" />
            {{ t('dupli', 'Delete all but one protected copy in every selected group') }}
          </label>
        </div>
        </div>
        <NcButton type="secondary" @click="doRemove">{{ t('dupli', 'Remove from list') }}</NcButton>
        <NcButton type="error" @click="showConfirm = true">
          🗑 {{ t('dupli', 'Delete duplicates') }}
        </NcButton>
      </div>
    </div>

    <div v-if="deleting" class="ud-deleting-overlay">
      <NcLoadingIcon :size="48" />
      <p>{{ stopRequested ? t('dupli', 'Stopping after current batch…') : t('dupli', 'Deleting duplicates, please wait…') }}</p>
      <div v-if="bulkTotal > 0" class="ud-bulk-progress">
        <div class="ud-bulk-progress__bar">
          <div class="ud-bulk-progress__fill" :style="{ width: (bulkProgress / bulkTotal * 100) + '%' }"></div>
        </div>
        <div class="ud-bulk-progress__text">
          {{ bulkProgress }} / {{ bulkTotal }} {{ t('dupli', 'groups processed') }} · {{ bulkDeletedCount }} {{ t('dupli', 'files deleted') }}
        </div>
      </div>
      <button class="ud-stop-btn" :disabled="stopRequested" @click="stopRequested = true">
        {{ stopRequested ? t('dupli', 'Stopping…') : ('⏹ ' + t('dupli', 'Stop')) }}
      </button>
    </div>
    <div v-if="deleteResult && !deleting" class="ud-delete-result">
      ✅ {{ deleteResult.deleted }} {{ t('dupli', 'files deleted') }}
      <span v-if="deleteResult.skipped > 0"> · {{ deleteResult.skipped }} {{ t('dupli', 'skipped') }}</span>
      <span v-if="deleteResult.conflicts && deleteResult.conflicts.length > 0" class="ud-conflict-badge">
        · ⚠️ {{ deleteResult.conflicts.length }} {{ t('dupli', 'conflicts need review') }}
      </span>
      <button class="ud-link-btn" @click="deleteResult = null">✕</button>
    </div>
    <div v-show="!deleting">
    <div v-if="groupsLoading" class="ud-loading"><NcLoadingIcon /></div>
    <div v-else-if="groups.length === 0" class="ud-empty">
      <p v-if="currentTask && currentTask.finished_time > 0">{{ t('dupli', 'No duplicates found') }} 🎉</p>
      <p v-else>{{ t('dupli', 'Scan is still running or has not started yet.') }}</p>
    </div>

    <div v-else>
      <div class="ud-groups">
        <GroupCard
          v-for="group in groups"
          :key="group.group_id"
          :group="group"
          :task-id="Number(id)"
          :selected="isGroupSelected(group.group_id)"
          :delete-protected-duplicates="deleteProtectedFor.includes(group.group_id)"
          @toggle="toggleGroup(group.group_id)"
          @file-deleted="reload"
          @protected-dupe-change="onProtectedDupeChange" />
      </div>

      </div><!-- end v-show !deleting -->
    <div class="ud-pagination" v-if="!deleting && totals && Number(totals.groupstotal) > limit">
        <NcButton :disabled="page === 0" @click="goPrev">← {{ t('dupli', 'Prev') }}</NcButton>
        <span class="ud-page-info">{{ page + 1 }} / {{ totalPages }}</span>
        <NcButton :disabled="!hasNextPage" @click="goNext">{{ t('dupli', 'Next') }} →</NcButton>
      </div>
    </div>

    <!-- Confirm delete modal -->
    <NcModal v-if="showConfirm" @closing="showConfirm = false">
      <div class="ud-modal-content">
        <h3>{{ t('dupli', 'Confirm bulk deletion') }}</h3>
        <div class="ud-confirm-summary">
          <div class="ud-confirm-row">
            <span>{{ t('dupli', 'Groups') }}</span>
            <strong>{{ allGroupsSelected ? allSelectedIds.length : selectedGroups.size }}</strong>
          </div>
          <div class="ud-confirm-row ud-confirm-row--savings">
            <span>{{ t('dupli', 'Storage freed') }}</span>
            <strong class="ud-savings-amount">~{{ formatBytes(estimatedSavings) }}</strong>
          </div>
          <div class="ud-confirm-row" v-if="protectedSkipCount !== 0">
            <span>🛡 {{ t('dupli', 'Protected files kept') }}</span>
            <strong>{{ protectedSkipCount === -1 ? t('dupli', 'Protected files will be kept') : protectedSkipCount }}</strong>
          </div>
          <div class="ud-confirm-row" v-if="deleteProtectedFor.length > 0">
            <span>⚠️ {{ t('dupli', 'Groups where protected duplicates will be reduced') }}</span>
            <strong>{{ deleteProtectedFor.length }}</strong>
          </div>
          <div class="ud-confirm-note">
            {{ t('dupli', 'All unprotected duplicates will be deleted. Protected files are kept unless you opted in above.') }}
          </div>
        </div>
        <div class="ud-form-actions">
          <NcButton @click="showConfirm = false">{{ t('dupli', 'Cancel') }}</NcButton>
          <NcButton type="error" @click="executeBulk">
            🗑 {{ t('dupli', 'Delete now') }} (~{{ formatBytes(estimatedSavings) }})
          </NcButton>
        </div>
      </div>
    </NcModal>

    <!-- Rule 4: Conflict resolution modal -->
    <NcModal v-if="currentConflict" @closing="skipConflict">
      <div class="ud-modal-content ud-conflict-modal">
        <h3>⚠️ {{ t('dupli', 'Conflict') }} — {{ t('dupli', 'Group') }} {{ currentConflict.group_id }}</h3>
        <p class="ud-conflict-desc">
          {{ t('dupli', 'The largest unprotected file is bigger than the largest protected file. Choose which file to keep — all others will be permanently deleted.') }}
        </p>
        <p class="ud-conflict-progress">
          {{ conflictIndex + 1 }} / {{ conflicts.length }}
        </p>

        <div class="ud-conflict-files">
          <label
            v-for="file in currentConflict.files"
            :key="file.id"
            :class="['ud-conflict-file', { 'ud-conflict-file--protected': file.protected, 'ud-conflict-file--selected': conflictKeepFileId === file.id }]">
            <input type="radio" :value="file.id" v-model="conflictKeepFileId" />
            <img
              :src="conflictThumb(file.fileid)"
              class="ud-conflict-thumb"
              @error="e => e.target.style.display='none'" />
            <div class="ud-conflict-file-info">
              <div class="ud-conflict-file-name" :title="file.filename">{{ file.filename }}</div>
              <div class="ud-conflict-file-path">{{ shortPath(file.filepath) }}</div>
              <div class="ud-conflict-file-size">{{ formatBytes(file.filesize) }}</div>
              <span v-if="file.protected" class="ud-conflict-protected-tag">🛡 {{ t('dupli', 'Protected') }}</span>
            </div>
          </label>
        </div>

        <div class="ud-form-actions">
          <NcButton @click="skipConflict">{{ t('dupli', 'Skip this group') }}</NcButton>
          <NcButton type="error" :disabled="!conflictKeepFileId || resolvingConflict" @click="resolveConflict">
            {{ resolvingConflict ? t('dupli', 'Deleting…') : t('dupli', 'Keep selected & delete others') }}
          </NcButton>
        </div>
      </div>
    </NcModal>
  </div>
</template>

<script>
import { NcButton, NcModal, NcLoadingIcon } from '@nextcloud/vue'
import { mapGetters, mapActions } from 'vuex'
import axios from '@nextcloud/axios'
import { generateUrl } from '@nextcloud/router'
import GroupCard from '../components/details/GroupCard.vue'

export default {
  name: 'TaskDetail',
  components: { NcButton, NcModal, NcLoadingIcon, GroupCard },
  props: { id: { type: String, required: true } },
  data() {
    return {
      showConfirm: false,
      deleting: false,
      deleteResult: null,
      allGroupsSelected: false,
      allSelectedIds: [],
      deleteProtectedFor: [],
      bulkProgress: 0,
      bulkTotal: 0,
      bulkDeletedCount: 0,
      deleteUnprotectedAndKeepOne: false,
      selectAllProtected: false,
      keepFromFolder: '',
      filterPattern: '',
      activeFilter: '',
      // Rule 4: conflict resolution state
      conflicts: [],
      conflictIndex: 0,
      conflictKeepFileId: null,
      resolvingConflict: false,
      // Stop button
      stopRequested: false,
    }
  },
  computed: {
    ...mapGetters(['currentTask', 'groups', 'totals', 'groupsLoading', 'selectedGroups', 'page', 'limit', 'rules']),
    allCurrentSelected() {
      return this.groups.length > 0 && this.groups.every(g => this.isGroupSelected(g.group_id))
    },
    hasNextPage() {
      if (!this.totals) return false
      return (this.page + 1) * this.limit < Number(this.totals.groupstotal)
    },
    totalPages() {
      if (!this.totals) return 1
      return Math.ceil(Number(this.totals.groupstotal) / this.limit)
    },
    activeGroupIds() {
      return this.allGroupsSelected ? this.allSelectedIds : [...this.selectedGroups]
    },
    selectedGroupsData() {
      if (this.allGroupsSelected) return this.groups
      return this.groups.filter(g => this.selectedGroups.has(g.group_id))
    },
    // Rule 4: current conflict being resolved
    currentConflict() {
      if (!this.conflicts.length || this.conflictIndex >= this.conflicts.length) return null
      return this.conflicts[this.conflictIndex]
    },
    estimatedSavings() {
      if (!this.selectedGroups.size && !this.allGroupsSelected) return 0

      const stripMount = (path) => {
        if (!path) return ''
        const parts = path.replace(/^\/+/, '').split('/')
        return parts.slice(1).join('/')
      }
      const keepPath = stripMount(this.keepFromFolder)

      const matchesKeep = (filepath) => {
        if (!keepPath) return false
        const fp = (filepath || '').replace(/^\/+/, '')
        return fp === keepPath || fp.startsWith(keepPath + '/')
      }

      let total = 0
      const groupsToCheck = this.allGroupsSelected
        ? this.groups
        : this.groups.filter(g => this.isGroupSelected(g.group_id))

      for (const group of groupsToCheck) {
        const files = group.files || []
        const unprotected = files.filter(f => !f.protected)
        const protected_ = files.filter(f => f.protected)

        total += unprotected.reduce((s, f) => s + Number(f.filesize || 0), 0)

        if (this.deleteUnprotectedAndKeepOne && this.keepFromFolder && protected_.length >= 1) {
          const inKeep = protected_.filter(f => matchesKeep(f.filepath))
          const notInKeep = protected_.filter(f => !matchesKeep(f.filepath))
          total += notInKeep.reduce((s, f) => s + Number(f.filesize || 0), 0)
          if (inKeep.length > 1) {
            total += inKeep.slice(1).reduce((s, f) => s + Number(f.filesize || 0), 0)
          }
        }
      }

      if (this.allGroupsSelected && this.totals && this.groups.length > 0) {
        const ratio = Number(this.totals.groupstotal) / this.groups.length
        total = Math.round(total * ratio)
      }
      return total
    },
    protectedSkipCount() {
      if (this.allGroupsSelected) return -1
      let count = 0
      for (const group of this.selectedGroupsData) {
        const protectedFiles = (group.files || []).filter(f => f.protected)
        if (this.deleteProtectedFor.includes(group.group_id)) {
          count += 1
        } else {
          count += protectedFiles.length
        }
      }
      return count
    },
  },
  created() { this.reload() },
  methods: {
    ...mapActions(['getTask', 'getGroups', 'bulkDelete', 'bulkRemove', 'getRules']),

    async reload() {
      this.$store.commit('clearSelection')
      this.allGroupsSelected = false
      this.allSelectedIds = []
      this.deleteProtectedFor = []
      this.selectAllProtected = false
      await this.getTask(this.id)
      await this.getGroups({ taskId: this.id, filter: this.activeFilter })
      if (!this.rules || !this.rules.length) await this.getRules()
    },

    isGroupSelected(groupId) {
      return this.allGroupsSelected || this.selectedGroups.has(groupId)
    },

    toggleGroup(groupId) {
      if (this.allGroupsSelected) {
        this.allGroupsSelected = false
        this.allSelectedIds = []
        this.groups.forEach(g => {
          if (g.group_id !== groupId) this.$store.commit('toggleGroup', g.group_id)
        })
      } else {
        this.$store.commit('toggleGroup', groupId)
      }
    },

    toggleCurrentPage() {
      if (this.allGroupsSelected) {
        this.clearAllSelection()
      } else if (this.allCurrentSelected) {
        this.$store.commit('clearSelection')
      } else {
        this.$store.commit('clearSelection')
        this.groups.forEach(g => this.$store.commit('toggleGroup', g.group_id))
      }
    },

    onSelectAllProtected() {
      if (this.selectAllProtected) {
        this.deleteProtectedFor = [...this.activeGroupIds]
      } else {
        this.deleteProtectedFor = []
      }
    },

    async selectAllPages() {
      try {
        const res = await axios.get(generateUrl(`/apps/urbanduplicati/api/v1/tasks/${this.id}/all-group-ids`) + (this.activeFilter ? `?filter=${encodeURIComponent(this.activeFilter)}` : ''))
        this.allSelectedIds = res.data.group_ids || []
        this.allGroupsSelected = true
        this.$store.commit('clearSelection')
        this.groups.forEach(g => this.$store.commit('toggleGroup', g.group_id))
      } catch(e) {
        console.error('Failed to fetch all group IDs', e)
      }
    },

    clearAllSelection() {
      this.allGroupsSelected = false
      this.allSelectedIds = []
      this.$store.commit('clearSelection')
    },

    onProtectedDupeChange({ groupId, value }) {
      if (value) {
        if (!this.deleteProtectedFor.includes(groupId)) {
          this.deleteProtectedFor = [...this.deleteProtectedFor, groupId]
        }
      } else {
        this.deleteProtectedFor = this.deleteProtectedFor.filter(id => id !== groupId)
      }
    },

    applyFilter() {
      this.activeFilter = this.filterPattern.trim()
      this.$store.commit('setPage', 0)
      this.$store.commit('clearSelection')
      this.getGroups({ taskId: this.id, filter: this.activeFilter })
    },
    clearFilter() {
      this.filterPattern = ''
      this.activeFilter = ''
      this.$store.commit('setPage', 0)
      this.getGroups({ taskId: this.id, filter: '' })
    },
    goPrev() {
      this.$store.commit('setPage', this.page - 1)
      this.$store.commit('clearSelection')
      this.allGroupsSelected = false
      this.getGroups({ taskId: this.id, filter: this.activeFilter })
    },

    goNext() {
      this.$store.commit('setPage', this.page + 1)
      this.$store.commit('clearSelection')
      this.allGroupsSelected = false
      this.getGroups({ taskId: this.id, filter: this.activeFilter })
    },

    async doRemove() {
      await this.bulkRemove({ taskId: this.id, groupIds: this.activeGroupIds })
      this.$store.commit('setPage', 0)
      this.clearAllSelection()
      await this.getGroups({ taskId: this.id, filter: this.activeFilter })
    },

    async executeBulk() {
      this.showConfirm = false
      await this.$nextTick()
      this.deleting = true
      this.deleteResult = null
      try {
        console.log('bulkDelete groupIds:', this.activeGroupIds, 'length:', this.activeGroupIds.length)
        const effectiveDeleteProtectedFor = this.deleteUnprotectedAndKeepOne && this.keepFromFolder
          ? this.activeGroupIds
          : this.deleteProtectedFor

        this.bulkTotal = this.activeGroupIds.length
        this.bulkProgress = 0
        this.bulkDeletedCount = 0
        this.stopRequested = false
        const res = await this.$store.dispatch('bulkDelete', {
          taskId: this.id,
          groupIds: this.activeGroupIds,
          deleteProtectedFor: effectiveDeleteProtectedFor,
          deleteUnprotectedAndKeepOne: this.deleteUnprotectedAndKeepOne,
          keepFromFolder: this.keepFromFolder,
          filterPattern: this.activeFilter,
          onProgress: (done, total, deleted) => {
            this.bulkProgress = done
            this.bulkTotal = total
            this.bulkDeletedCount = deleted
          },
          shouldStop: () => this.stopRequested,
        })
        if (res) {
          this.deleteResult = res
          // Rule 4: if there are conflicts, start resolution flow
          if (res.conflicts && res.conflicts.length > 0) {
            this.conflicts = res.conflicts
            this.conflictIndex = 0
            this.conflictKeepFileId = null
          }
        }
      } catch (e) {
        console.error('Bulk delete error:', e)
      } finally {
        this.deleting = false
        await this.$nextTick()
        this.$store.commit('setPage', 0)
        this.clearAllSelection()
        this.deleteProtectedFor = []
        this.selectAllProtected = false
        this.deleteUnprotectedAndKeepOne = false
        this.keepFromFolder = ''
        this.stopRequested = false
        await this.getGroups({ taskId: this.id, filter: this.activeFilter })
      }
    },

    // ── Rule 4: Conflict resolution ──────────────────────────────────────────

    conflictThumb(fileId) {
      return generateUrl('/core/preview?fileId=' + fileId + '&x=120&y=120&a=1&forceIcon=0')
    },

    skipConflict() {
      this.conflictIndex++
      this.conflictKeepFileId = null
      if (this.conflictIndex >= this.conflicts.length) {
        this.conflicts = []
        this.conflictIndex = 0
      }
    },

    async resolveConflict() {
      if (!this.conflictKeepFileId || this.resolvingConflict) return
      this.resolvingConflict = true
      try {
        const conflict = this.currentConflict
        // Delete every file in this group EXCEPT the chosen one
        for (const file of conflict.files) {
          if (file.id === this.conflictKeepFileId) continue
          try {
            await axios.delete(
              generateUrl(`/apps/urbanduplicati/api/v1/tasks/${conflict.task_id}/groups/${conflict.group_id}/files/${file.id}`) + '?force_delete=1'
            )
          } catch (e) {
            console.warn('Could not delete file in conflict resolution:', file.id, e)
          }
        }
        // Advance to next conflict
        this.conflictIndex++
        this.conflictKeepFileId = null
        if (this.conflictIndex >= this.conflicts.length) {
          this.conflicts = []
          this.conflictIndex = 0
          await this.getGroups({ taskId: this.id, filter: this.activeFilter })
        }
      } finally {
        this.resolvingConflict = false
      }
    },

    formatBytes(b) {
      if (!b) return '0 B'; b = Number(b)
      if (b >= 1073741824) return (b / 1073741824).toFixed(1) + ' GB'
      if (b >= 1048576) return (b / 1048576).toFixed(1) + ' MB'
      if (b >= 1024) return Math.round(b / 1024) + ' KB'
      return b + ' B'
    },
    shortPath(p) {
      if (!p) return ''
      const parts = p.split('/').filter(Boolean)
      return parts.length > 3 ? '…/' + parts.slice(-2).join('/') : p
    },
  },
}
</script>

<style scoped>
.ud-page { padding: 20px 40px; max-width: 1000px; margin: 0 auto; }
.ud-page-header { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
.ud-page-header h2 { margin: 0; font-size: 1.3em; font-weight: 600; flex: 1; }
.ud-header-meta { font-size: 0.85em; color: var(--color-text-maxcontrast); }
.ud-loading, .ud-empty { text-align: center; padding: 40px; color: var(--color-text-maxcontrast); }
.ud-groups { margin-top: 8px; }

.ud-bulk-toolbar {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; background: var(--color-background-dark);
  border-radius: 10px; margin-bottom: 16px; flex-wrap: wrap;
}
.ud-check-all { display: flex; align-items: center; gap: 8px; cursor: pointer; font-weight: 500; flex: 1; }
.ud-select-status { font-size: 0.85em; }
.ud-select-status--all { color: var(--color-primary); font-weight: 600; }
.ud-link-btn {
  background: none; border: none; cursor: pointer;
  color: var(--color-primary); text-decoration: underline; font-size: inherit; padding: 0 4px;
}
.ud-bulk-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ud-savings-badge {
  background: var(--color-main-background); border: 1px solid var(--color-border);
  border-radius: 20px; padding: 4px 14px; font-size: 0.85em; font-weight: 600;
}
.ud-savings-protected { color: #f8a800; font-weight: 400; }

.ud-pagination {
  display: flex; align-items: center; gap: 12px;
  justify-content: center; margin: 24px 0 40px;
  padding: 12px; background: var(--color-background-dark);
  border-radius: 10px;
}
.ud-page-info { font-weight: 500; min-width: 80px; text-align: center; }

.ud-modal-content { padding: 28px; min-width: 380px; }
.ud-modal-content h3 { margin: 0 0 20px; font-size: 1.1em; }
.ud-confirm-summary { background: var(--color-background-dark); border-radius: 10px; padding: 16px; margin-bottom: 20px; }
.ud-confirm-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--color-border); font-size: 0.9em; }
.ud-confirm-row:last-of-type { border-bottom: none; }
.ud-savings-amount { font-size: 1.2em; color: #46ba61; }
.ud-confirm-note { margin-top: 10px; font-size: 0.8em; color: var(--color-text-maxcontrast); font-style: italic; }
.ud-form-actions { display: flex; gap: 8px; justify-content: flex-end; }
.ud-filter-bar {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-bottom: 12px; padding: 10px 14px;
  background: var(--color-background-dark); border-radius: 10px;
}
.ud-filter-input {
  flex: 1; min-width: 200px; padding: 6px 12px;
  border: 1px solid var(--color-border); border-radius: 6px;
  background: var(--color-main-background); font-size: 0.9em;
}
.ud-filter-active { font-size: 0.85em; color: var(--color-primary); }
.ud-deleting-overlay {
  text-align: center; padding: 40px;
  display: flex; flex-direction: column; align-items: center; gap: 16px;
  background: var(--color-background-dark); border-radius: 12px; margin: 16px 0;
  color: var(--color-text-maxcontrast);
}
.ud-delete-result {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; background: rgba(70,186,97,0.12);
  border: 1px solid #46ba61; border-radius: 10px; margin-bottom: 12px;
  font-weight: 500; color: #46ba61;
}
.ud-conflict-badge { color: #f8a800; font-weight: 600; }
.ud-keep-folder-row {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  width: 100%; padding: 8px 0; border-top: 1px solid var(--color-border); margin-top: 4px;
}
.ud-keep-folder-label { display: flex; align-items: center; gap: 6px; font-size: 0.85em; cursor: pointer; }
.ud-keep-folder-select { font-size: 0.85em; padding: 4px 8px; border-radius: 6px; border: 1px solid var(--color-border); background: var(--color-main-background); }
.ud-bulk-progress {
  width: 100%; max-width: 400px; margin-top: 16px;
}
.ud-bulk-progress__bar {
  width: 100%; height: 8px; background: rgba(255,255,255,0.2);
  border-radius: 4px; overflow: hidden;
}
.ud-bulk-progress__fill {
  height: 100%; background: var(--color-primary-element);
  border-radius: 4px; transition: width 0.3s ease;
}
.ud-bulk-progress__text {
  margin-top: 8px; font-size: 0.85em;
  color: var(--color-main-text); text-align: center;
}
.ud-stop-btn {
  margin-top: 16px; padding: 8px 28px;
  border-radius: 8px; border: 2px solid var(--color-error);
  background: transparent; color: var(--color-error);
  font-size: 0.95em; font-weight: 700; cursor: pointer;
  transition: background 0.2s, color 0.2s;
}
.ud-stop-btn:hover:not(:disabled) { background: var(--color-error); color: #fff; }
.ud-stop-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* Rule 4: Conflict resolution modal */
.ud-conflict-modal { max-width: 680px; }
.ud-conflict-desc {
  font-size: 0.9em; color: var(--color-text-maxcontrast);
  margin: 0 0 8px; line-height: 1.5;
}
.ud-conflict-progress {
  font-size: 0.82em; color: var(--color-text-maxcontrast);
  margin: 0 0 16px; font-weight: 600;
}
.ud-conflict-files {
  display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px;
}
.ud-conflict-file {
  display: flex; flex-direction: column; align-items: center;
  width: 140px; border: 2px solid var(--color-border);
  border-radius: 8px; overflow: hidden; cursor: pointer;
  background: var(--color-background-dark); padding-bottom: 8px;
  transition: border-color 0.15s;
}
.ud-conflict-file input[type="radio"] { margin: 8px 0 4px; }
.ud-conflict-file--protected { border-color: #f8a800; }
.ud-conflict-file--selected { border-color: var(--color-primary); box-shadow: 0 0 0 2px var(--color-primary-element-light); }
.ud-conflict-thumb {
  width: 120px; height: 100px; object-fit: cover; border-radius: 4px;
}
.ud-conflict-file-info { padding: 4px 6px; text-align: center; width: 100%; }
.ud-conflict-file-name {
  font-size: 0.75em; font-weight: 600; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; margin-bottom: 2px;
}
.ud-conflict-file-path {
  font-size: 0.65em; color: var(--color-text-maxcontrast);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ud-conflict-file-size { font-size: 0.7em; color: var(--color-text-maxcontrast); }
.ud-conflict-protected-tag { font-size: 0.65em; color: #f8a800; font-weight: 600; }
</style>
