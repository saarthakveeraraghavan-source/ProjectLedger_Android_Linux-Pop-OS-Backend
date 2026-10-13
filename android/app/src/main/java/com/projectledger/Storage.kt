package com.projectledger

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.room.*
import kotlinx.coroutines.flow.Flow
import net.zetetic.database.sqlcipher.SupportOpenHelperFactory
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class Vault(context: Context) {
    internal val appContext = context.applicationContext
    private val prefs = context.getSharedPreferences("vault", Context.MODE_PRIVATE)
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("ledger-vault-v1", null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("ledger-vault-v1", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .apply { if (android.os.Build.VERSION.SDK_INT >= 28) setUnlockedDeviceRequired(true) }.build())
        }.generateKey()
    }
    fun get(name: String): String? {
        val encoded = prefs.getString(name, null) ?: return null
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        return String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)
    }
    fun put(name: String, value: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        check(prefs.edit().putString(name, Base64.encodeToString(cipher.iv + cipher.doFinal(value.toByteArray()), Base64.NO_WRAP)).commit())
    }
    fun remove(name: String) { check(prefs.edit().remove(name).commit()) }
    fun databaseKey(user: String): ByteArray {
        var value = get("db-$user")
        if (value == null) {
            value = Base64.encodeToString(ByteArray(32).also { SecureRandom().nextBytes(it) }, Base64.NO_WRAP)
            put("db-$user", value)
        }
        return value.toByteArray(Charsets.UTF_8)
    }
}
@kotlinx.serialization.Serializable
@Entity data class LocalExpense(@PrimaryKey val id: String, val project: String, val payload: String,
    val serverVersion: Int = 0, val state: String = "local", val voided: Boolean = false,
    val owner: String = "", val createdAt: String = "", val updatedAt: String = "")
@Entity data class LocalProject(@PrimaryKey val id: String, val payload: String)
@kotlinx.serialization.Serializable
@Entity(indices = [Index("expenseId")]) data class Outbox(@PrimaryKey val id: String,
    val expenseId: String, val payload: String, val created: Long, val conflict: String? = null)
@kotlinx.serialization.Serializable
@Entity data class PendingAI(@PrimaryKey val id: String, val project: String, val text: String,
    val referenceDate: String, val state: String = "pending", val result: String? = null, val error: String? = null,
    val confirmed: String = "")
@Entity data class Meta(@PrimaryKey val key: String, val value: String)
@Dao interface LedgerDao {
    @Query("SELECT * FROM LocalExpense ORDER BY createdAt DESC") fun observeExpenses(): Flow<List<LocalExpense>>
    @Query("SELECT * FROM LocalProject") fun observeProjects(): Flow<List<LocalProject>>
    @Query("SELECT * FROM PendingAI") fun observeAI(): Flow<List<PendingAI>>
    @Query("SELECT * FROM Outbox ORDER BY created,id") fun observeQueue(): Flow<List<Outbox>>
    @Query("SELECT * FROM Meta") fun observeMeta(): Flow<List<Meta>>
    @Query("SELECT * FROM LocalExpense WHERE id=:id") suspend fun expense(id: String): LocalExpense?
    @Query("SELECT * FROM LocalProject WHERE id=:id") suspend fun project(id: String): LocalProject?
    @Query("SELECT * FROM Outbox ORDER BY created,id") suspend fun queue(): List<Outbox>
    @Query("SELECT * FROM Outbox WHERE expenseId=:id ORDER BY created,id") suspend fun queued(id: String): List<Outbox>
    @Query("SELECT * FROM PendingAI WHERE state='pending'") suspend fun pending(): List<PendingAI>
    @Query("SELECT * FROM PendingAI WHERE id=:id") suspend fun ai(id: String): PendingAI?
    @Query("SELECT * FROM Meta WHERE `key` LIKE 'project-change-%' ORDER BY `key`") suspend fun projectChanges(): List<Meta>
    @Query("DELETE FROM Meta WHERE `key`=:key") suspend fun removeMeta(key: String)
    @Query("SELECT value FROM Meta WHERE `key`=:key") suspend fun meta(key: String): String?
    @Upsert suspend fun save(expense: LocalExpense)
    @Upsert suspend fun saveProject(project: LocalProject)
    @Upsert suspend fun enqueue(operation: Outbox)
    @Upsert suspend fun saveAI(entry: PendingAI)
    @Upsert suspend fun saveMeta(meta: Meta)
    @Query("DELETE FROM Outbox WHERE id=:id") suspend fun acknowledge(id: String)
    @Query("DELETE FROM Outbox WHERE expenseId=:id") suspend fun clearQueue(id: String)
    @Query("DELETE FROM LocalExpense WHERE id=:id AND state='draft'") suspend fun removeDraft(id: String)
    @Query("DELETE FROM LocalProject WHERE id NOT IN (:ids)") suspend fun removeUnauthorizedProjects(ids: List<String>)
    @Query("UPDATE LocalExpense SET state='access_removed' WHERE project NOT IN (:ids)") suspend fun hideUnauthorized(ids: List<String>)
}
@Database(entities = [LocalExpense::class, LocalProject::class, Outbox::class, PendingAI::class, Meta::class], version = 1, exportSchema = true)
abstract class LedgerDatabase : RoomDatabase() {
    abstract fun dao(): LedgerDao
    companion object {
        fun open(context: Context, user: String, vault: Vault, base: String): LedgerDatabase {
            java.util.UUID.fromString(user)
            val identity = user + "-" + java.security.MessageDigest.getInstance("SHA-256").digest(base.toByteArray()).joinToString("") { "%02x".format(it) }

            System.loadLibrary("sqlcipher")
            return Room.databaseBuilder(context, LedgerDatabase::class.java, "ledger-$identity.db")
                .openHelperFactory(SupportOpenHelperFactory(vault.databaseKey(identity))).build()
        }
    }
}
