package platform

import (
	"fmt"
	"time"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	gormlogger "gorm.io/gorm/logger"
)

// OpenDB membuka GORM + pgx. PrepareStmt (extended protocol, prepared statement) aktif.
// SkipDefaultTransaction: satu statement sudah atomik; tanpa itu GORM membungkus INSERT/UPDATE
// dengan BEGIN/COMMIT sehingga jumlah query per request berbeda dari Fluent (gerbang kesetaraan #2).
func OpenDB(c Config) (*gorm.DB, error) {
	dsn := fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s sslmode=disable TimeZone=UTC",
		c.DBHost, c.DBPort, c.DBUser, c.DBPass, c.DBName)
	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{
		PrepareStmt:            true,
		SkipDefaultTransaction: true,
		Logger:                 gormlogger.Default.LogMode(gormlogger.Silent), // error DB tetap dicatat handler lewat loghttp (satu jalur log: LogLayer),
		NowFunc:                func() time.Time { return time.Now().UTC() },
	})
	if err != nil {
		return nil, err
	}
	sqlDB, err := db.DB()
	if err != nil {
		return nil, err
	}
	sqlDB.SetMaxOpenConns(c.DBPool)
	sqlDB.SetMaxIdleConns(c.DBPool)
	sqlDB.SetConnMaxLifetime(0)
	return db, nil
}
