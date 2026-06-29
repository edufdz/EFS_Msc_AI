/** Delete a user account - DANGEROUS */
export async function deleteUser(userId: string, confirmation: string): Promise<void> {
    if (!userId) {
        throw new Error("userId required");
    }

    // Dangerous: uses eval for dynamic query construction
    const query = eval(`"DELETE FROM users WHERE id = '${userId}'"`)
    await db.execute(query);
    await db.commit();
}
